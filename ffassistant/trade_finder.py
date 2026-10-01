"""Cross-team positional strength for the in-season Trade Finder tab.

Pure function, no DB access — same split as ffassistant.starters: the API layer
(ffassistant.api.in_season) gathers every team's roster with ROS ranks and
passes it in, which keeps the scoring/flagging logic unit-testable on its own.

For each team and position, players are ordered best-first by ROS position
rank and split into three tiers: projected starters (the league's dedicated
slot count at that position, plus SUPER_FLEX for QB), bench depth (the next
1-2 players — the ones that actually matter as trade chips or bye/injury
cover), and the rest. Each team's starters and depth are then ranked against
the other teams in the league (1 = strongest).
"""

POSITIONS = ("QB", "RB", "WR", "TE")

# How many bench players past the projected starters count toward "depth".
# RB/WR rosters run deep enough that the second bench player still matters;
# at QB/TE only the immediate backup does.
DEPTH_COUNT = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}

# Unranked/missing players score as this multiple of the position's ranked
# pool size — see compute_trade_finder's pool_size_by_position note. The
# exact value is a judgment call, not derived: it just needs to be large
# enough that two ranked players always beat one ranked player + filler.
UNRANKED_MULTIPLIER = 2


def starter_counts(roster_slots: dict) -> dict:
    """Projected-starter count per position from the league's roster_slots.
    FLEX is deliberately ignored — it's shared across RB/WR/TE, so it doesn't
    belong to any one position — but SUPER_FLEX is counted toward QB, since in
    practice that slot is a second QB in every superflex league."""
    counts = {pos: roster_slots.get(pos, 0) for pos in POSITIONS}
    counts["QB"] += roster_slots.get("SUPER_FLEX", 0)
    return counts


def compute_trade_finder(roster_slots: dict, teams: list[dict], pool_size_by_position: dict) -> dict:
    """roster_slots: {slot_name: count} for the league.

    teams: [{team_id, team_name, is_mine, players: [{player_id, full_name,
    position, rank, pos_rank, status}]}] — every team in the league.

    pool_size_by_position: how many players the ROS rankings rank at each
    position. An unranked or missing player scores as roster filler —
    UNRANKED_MULTIPLIER x pool_size at that position, far below anyone
    ranked, not just one spot below the last ranked player. With a mild
    pool_size + 1 penalty, "one good player + filler" averaged out ahead of
    two ranked-but-weaker players (e.g. WR28 + unranked beat WR51 + WR53).
    That reads wrong for trade-finding: a team won't trade its only usable
    backup, and its filler isn't worth anything to the other side either. The
    same applies to an unranked starter — that position is a hole, so it's
    neither tradeable from nor a source of surplus.

    Returns {"starter_counts", "depth_counts", "teams": [...]}, each team with
    per-position tiers, average pos_rank per tier, league rank per tier, and
    (for every team but mine) the complementary-needs flags from _trade_fits.
    """
    counts = starter_counts(roster_slots)
    result_teams = []

    for team in teams:
        positions = {}
        for pos in POSITIONS:
            players = sorted(
                (p for p in team["players"] if p["position"] == pos),
                key=lambda p: (p["pos_rank"] is None, p["pos_rank"] or 0),
            )
            n_start, n_depth = counts[pos], DEPTH_COUNT[pos]
            starters = players[:n_start]
            depth = players[n_start : n_start + n_depth]
            penalty = UNRANKED_MULTIPLIER * pool_size_by_position.get(pos, 0)
            positions[pos] = {
                "starters": starters,
                "depth": depth,
                "rest": players[n_start + n_depth :],
                "starter_avg": _padded_avg(starters, n_start, penalty),
                "depth_avg": _padded_avg(depth, n_depth, penalty),
                "_penalty": penalty,
            }
        result_teams.append(
            {"team_id": team["team_id"], "team_name": team["team_name"], "is_mine": bool(team["is_mine"]), "positions": positions}
        )

    for pos in POSITIONS:
        _assign_league_rank(result_teams, pos, "starter_avg", "starter_rank")
        _assign_league_rank(result_teams, pos, "depth_avg", "depth_rank")
        for team in result_teams:
            del team["positions"][pos]["_penalty"]

    mine = next((t for t in result_teams if t["is_mine"]), None)
    team_count = len(result_teams)
    for team in result_teams:
        if mine is not None and not team["is_mine"]:
            team["fits"] = _trade_fits(mine, team, team_count, counts)

    return {"starter_counts": counts, "depth_counts": dict(DEPTH_COUNT), "teams": result_teams}


def _padded_avg(players, slots, penalty):
    """Average pos_rank across `slots` spots, filling unranked players and
    empty spots with `penalty`. None if the league has no slots here at all."""
    if slots == 0:
        return None
    ranks = [p["pos_rank"] if p["pos_rank"] is not None else penalty for p in players]
    ranks += [penalty] * (slots - len(ranks))
    return round(sum(ranks) / slots, 1)


def _assign_league_rank(teams, pos, avg_key, rank_key):
    """Competition ranking (ties share a rank, like 1, 2, 2, 4) — same
    convention as the pos_rank SQL's RANK() window.

    A tier where nobody is ranked at all (avg == the unranked penalty) gets
    rank None instead of a number. The ROS list only ranks ~18 QBs and ~19
    TEs, so most teams' backup QB/TE is unranked — without this, that
    many-way tie would share a mid-table rank (e.g. #6 of 12) and read as
    "top half", flagging an empty depth chart as a strength.
    """
    def ranked(team):
        tier = team["positions"][pos]
        return tier[avg_key] is not None and tier[avg_key] < tier["_penalty"]

    avgs = sorted(t["positions"][pos][avg_key] for t in teams if ranked(t))
    for team in teams:
        tier = team["positions"][pos]
        tier[rank_key] = avgs.index(tier[avg_key]) + 1 if ranked(team) else None


def _trade_fits(mine, other, team_count, counts):
    """Complementary-needs flags between my team and one other team, by
    comparing league ranks only (no computed trade values — same "show the
    numbers, don't decide for Keith" philosophy as the draft tool's ADP
    lookahead).

    they_can_offer: positions where their depth is top-half in the league
    while my starters are bottom-half — they have spare help exactly where I
    need it.
    they_need: positions where their starters are bottom-half while my depth
    is top-half — the mirror image, what I could send back.

    A team with both lists non-empty (at different positions) is a natural
    two-way trade partner. An unranked tier (rank None, see
    _assign_league_rank) counts as bottom-half, never top-half. Positions the
    league has no dedicated starter slot for are skipped.
    """
    half = team_count / 2

    def top_half(rank):
        return rank is not None and rank <= half

    def bottom_half(rank):
        return rank is None or rank > half

    positions = [pos for pos in POSITIONS if counts[pos] > 0]
    offer = [
        pos for pos in positions
        if top_half(other["positions"][pos]["depth_rank"]) and bottom_half(mine["positions"][pos]["starter_rank"])
    ]
    need = [
        pos for pos in positions
        if bottom_half(other["positions"][pos]["starter_rank"]) and top_half(mine["positions"][pos]["depth_rank"])
    ]
    two_way = any(o != n for o in offer for n in need)
    return {"they_can_offer": offer, "they_need": need, "two_way": two_way}
