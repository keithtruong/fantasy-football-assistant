"""Weekly recap computation — pure functions over one week's box scores, no
DB access (same separation as ffassistant.starters: a caller a layer up
gathers rows from weekly_box_scores/teams/weekly_matchups, these functions
just compute — which keeps the logic itself unit-testable without a
database, and reusable regardless of which season/week the data came from).

Terminology used throughout: a "box score row" is one dict per rostered
player for one team for one week — {team_id, team_name, player_id,
full_name, position, slot_name, points} — matching a row of
weekly_box_scores joined to teams/players (see
ffassistant.ingest.espn.sync_box_scores). "Started" means slot_name not in
('BENCH', 'IR').

Waiver-wire "could've been a difference-maker" analysis (see
waiver_wire_difference_makers below) needs actual weekly fantasy points for
players nobody in the league rosters — an earlier pass through this project
assumed that was structurally unavailable, since box scores only ever
include rostered players. It isn't: ESPN's free-agent endpoint
(ffassistant.connectors.espn.get_free_agent_scores) returns the same
per-week point data for the unrostered pool, just from a different source
than box scores. It only works for the current/most-recent season, though
— ESPN doesn't reliably serve a free-agent pool for an old, completed
season, so this can't be backfilled against historical weeks the way box
scores can.
"""

import datetime
from collections import defaultdict

from ffassistant.starters import compute_starters

STARTED_EXCLUDED_SLOTS = ("BENCH", "IR")
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPERFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}
POSITION_SLOTS = ("QB", "RB", "WR", "TE", "DST", "K")  # "DEF" in fantasy-speak, DST in this project's schema

# Chronological order for the per-matchup "score at each checkpoint" story.
# "Other" catches anything that isn't Thu/Sun/Mon (an early-season Friday or
# international game) as well as any row with no game_date at all (a bye
# week, or a player ESPN couldn't resolve to a scheduled game) — it's last
# because it's mostly no-real-timing-information rather than "played late."
TIME_WINDOW_ORDER = (
    "Thursday Night",
    "Sunday Morning",
    "Sunday Afternoon",
    "Sunday Night",
    "Monday Night",
    "Other",
)


def time_window_for(game_date: str | None) -> str:
    """Buckets an ISO game_date string (as stored in weekly_box_scores, from
    ffassistant.connectors.espn.get_box_scores) into one of TIME_WINDOW_ORDER.

    Caveat worth knowing: espn_api resolves each kickoff with Python's
    datetime.fromtimestamp, which uses whatever machine synced the data's
    LOCAL system clock — there's no timezone captured alongside it. The hour
    thresholds below (14:00 / 18:00) are picked to comfortably separate
    early-window Sunday games (~1pm ET) from the late window (~4pm ET) from
    Sunday Night Football assuming that machine is on US Central time (which
    is where this league's owners are) — a sync from a different timezone
    would shift games across window boundaries. This is a real limitation,
    not a rounding error to silently paper over.
    """
    if not game_date:
        return "Other"
    dt = datetime.datetime.fromisoformat(game_date)
    weekday = dt.weekday()  # Monday=0 ... Sunday=6
    if weekday == 3:
        return "Thursday Night"
    if weekday == 0:
        return "Monday Night"
    if weekday == 6:
        if dt.hour < 14:
            return "Sunday Morning"
        if dt.hour < 18:
            return "Sunday Afternoon"
        return "Sunday Night"
    return "Other"


def score_by_checkpoint(team_box_scores: list[dict]) -> list[dict]:
    """For ONE team's box-score rows (started players only — a benched
    player's points never counted toward the actual matchup score at any
    point): a chronological series of {'window', 'points_this_window',
    'cumulative_points', 'players'} — the "how the week unfolded" story
    behind score_by_checkpoint's headline number, one entry per time window
    that team actually had a player active in (a window nobody played in is
    omitted, not shown as a flat/zero step). 'players' is that window's
    contributors, best-scorer-first.

    This is a retroactive reconstruction from final results, not true
    in-game/live tracking: a player's full final point total lands all at
    once at their game's window close, rather than accruing continuously
    through the actual game clock. See time_window_for's docstring for the
    timezone caveat that feeds into this.
    """
    started = [row for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS]

    points_by_window: dict[str, float] = defaultdict(float)
    players_by_window: dict[str, list[dict]] = defaultdict(list)
    for row in started:
        window = time_window_for(row.get("game_date"))
        points_by_window[window] += row["points"]
        players_by_window[window].append(
            {"player_id": row["player_id"], "full_name": row["full_name"], "points": row["points"]}
        )

    cumulative = 0.0
    series = []
    for window in TIME_WINDOW_ORDER:
        if window not in points_by_window:
            continue
        cumulative += points_by_window[window]
        series.append(
            {
                "window": window,
                "points_this_window": points_by_window[window],
                "cumulative_points": cumulative,
                "players": sorted(players_by_window[window], key=lambda p: p["points"], reverse=True),
            }
        )
    return series


def team_weekly_scores(box_scores: list[dict]) -> dict[int, float]:
    """{team_id: total started points} for the whole league that week —
    bench/IR excluded. This is the number every standings-style stat below
    (high/low, biggest win, closest matchup) reads from."""
    totals: dict[int, float] = defaultdict(float)
    for row in box_scores:
        if row["slot_name"] not in STARTED_EXCLUDED_SLOTS:
            totals[row["team_id"]] += row["points"]
    return dict(totals)


def high_low_scores(team_scores: dict[int, float], team_names: dict[int, str]) -> dict:
    """{'highest': {...}, 'lowest': {...}}, each {team_id, team_name, points}
    — both None if team_scores is empty (nothing synced yet)."""
    if not team_scores:
        return {"highest": None, "lowest": None}
    highest_id = max(team_scores, key=team_scores.get)
    lowest_id = min(team_scores, key=team_scores.get)
    return {
        "highest": {"team_id": highest_id, "team_name": team_names.get(highest_id), "points": team_scores[highest_id]},
        "lowest": {"team_id": lowest_id, "team_name": team_names.get(lowest_id), "points": team_scores[lowest_id]},
    }


def matchup_results(
    team_scores: dict[int, float], team_names: dict[int, str], matchup_pairs: list[tuple[int, int]]
) -> list[dict]:
    """One entry per real-world matchup — {team_a, team_b, margin}, each side
    {team_id, team_name, points} — collapsed from weekly_matchups' both-
    directions-stored pairs so each matchup appears once, not twice. A
    matchup where either side hasn't been scored yet (box scores not synced
    for that team) is skipped rather than guessed at.
    """
    seen = set()
    results = []
    for team_id, opponent_id in matchup_pairs:
        key = tuple(sorted((team_id, opponent_id)))
        if key in seen:
            continue
        seen.add(key)
        if team_id not in team_scores or opponent_id not in team_scores:
            continue
        a_score, b_score = team_scores[team_id], team_scores[opponent_id]
        results.append(
            {
                "team_a": {"team_id": team_id, "team_name": team_names.get(team_id), "points": a_score},
                "team_b": {"team_id": opponent_id, "team_name": team_names.get(opponent_id), "points": b_score},
                "margin": abs(a_score - b_score),
            }
        )
    return results


def biggest_win_and_closest_matchup(matchups: list[dict]) -> dict:
    """{'biggest_win', 'closest_matchup'} from matchup_results' output —
    both None if there are no scored matchups yet."""
    if not matchups:
        return {"biggest_win": None, "closest_matchup": None}
    return {
        "biggest_win": max(matchups, key=lambda m: m["margin"]),
        "closest_matchup": min(matchups, key=lambda m: m["margin"]),
    }


def top_performers_by_position(box_scores: list[dict], limit: int = 3) -> dict[str, list[dict]]:
    """{position: [{player_id, full_name, team_id, team_name, points}, ...]},
    best-first, across every rostered player regardless of slot — a monster
    bench day is still worth a callout, not just starters."""
    by_position: dict[str, list[dict]] = defaultdict(list)
    for row in box_scores:
        by_position[row["position"]].append(row)
    return {
        position: sorted(rows, key=lambda r: r["points"], reverse=True)[:limit] for position, rows in by_position.items()
    }


def best_team_by_slot(box_scores: list[dict], team_names: dict[int, str]) -> dict[str, dict]:
    """Which team's started players scored the most combined points that
    week, for each of QB/RB/WR/TE/DST/K plus BENCH.

    A player FLEX/SUPER_FLEX'd in is credited to their real position (an RB
    started at FLEX still counts toward that team's RB total) rather than
    dropped or bucketed separately — "best RB scores" should mean exactly
    that regardless of which slot the RB happened to fill. BENCH totals
    every benched player's points per team; IR is excluded from both (a
    parking spot, not really "the bench"). A position/BENCH bucket with no
    scored players yet is None rather than a misleading 0.

    Each result also carries 'players': every player who contributed to that
    winning team's total at this slot (best-scorer-first) — e.g. a team's
    best RB total is usually a dedicated RB plus a flexed-in RB, and callers
    want to name both, not just the combined number.
    """
    position_totals: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    position_players: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    bench_totals: dict[int, float] = defaultdict(float)
    bench_players: dict[int, list[dict]] = defaultdict(list)

    for row in box_scores:
        contributor = {"player_id": row["player_id"], "full_name": row["full_name"], "points": row["points"]}
        if row["slot_name"] == "BENCH":
            bench_totals[row["team_id"]] += row["points"]
            bench_players[row["team_id"]].append(contributor)
        elif row["slot_name"] != "IR":
            position_totals[row["position"]][row["team_id"]] += row["points"]
            position_players[row["position"]][row["team_id"]].append(contributor)

    result: dict[str, dict] = {}
    for position in POSITION_SLOTS:
        totals = position_totals.get(position, {})
        if not totals:
            result[position] = None
            continue
        best_team_id = max(totals, key=totals.get)
        players = sorted(position_players[position][best_team_id], key=lambda p: p["points"], reverse=True)
        result[position] = {
            "team_id": best_team_id,
            "team_name": team_names.get(best_team_id),
            "points": totals[best_team_id],
            "players": players,
        }

    if bench_totals:
        best_bench_id = max(bench_totals, key=bench_totals.get)
        players = sorted(bench_players[best_bench_id], key=lambda p: p["points"], reverse=True)
        result["BENCH"] = {
            "team_id": best_bench_id,
            "team_name": team_names.get(best_bench_id),
            "points": bench_totals[best_bench_id],
            "players": players,
        }
    else:
        result["BENCH"] = None

    return result


def optimal_lineup_pct(roster_slots: dict, team_box_scores: list[dict]) -> dict:
    """For ONE team's box-score rows (every rostered player that week,
    started or benched): what % of that roster's maximum possible points did
    the owner actually start? {'actual_points', 'optimal_points', 'pct'} —
    pct is None if optimal_points is 0 (nothing to divide by).

    Reuses ffassistant.starters.compute_starters — the exact same greedy
    dedicated-slots-then-FLEX-then-SUPER_FLEX assignment the pre-game
    Starters tab uses — but fed hindsight points instead of a pre-game rank,
    via a negated 'rank' (points is never None here, so the "lower rank
    wins, None sorts last" comparison it already does just picks the
    highest-scoring eligible player for each slot). That greedy order is
    provably optimal for this nested-eligibility slot structure (dedicated
    slots accept only one position; FLEX accepts more; SUPER_FLEX accepts
    the most), so this is the actual best possible lineup, not an
    approximation.
    """
    players = [
        {
            "player_id": row["player_id"],
            "full_name": row["full_name"],
            "position": row["position"],
            "rank": -row["points"],
            "flex_rank": -row["points"] if row["position"] in FLEX_ELIGIBLE else None,
            "op_rank": -row["points"] if row["position"] in SUPERFLEX_ELIGIBLE else None,
            "points": row["points"],
        }
        for row in team_box_scores
    ]

    optimal = compute_starters(roster_slots, players)
    optimal_points = sum(slot["player"]["points"] for slot in optimal["slots"] if slot["player"] is not None)
    actual_points = sum(row["points"] for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS)

    return {
        "actual_points": actual_points,
        "optimal_points": optimal_points,
        "pct": (actual_points / optimal_points * 100) if optimal_points else None,
    }


def start_sit_gaffes(team_box_scores: list[dict]) -> list[dict]:
    """For ONE team's box-score rows: every actual starter who was outscored
    by a benched teammate eligible for that exact slot — the "why did you
    bench the guy who went off" callouts. Eligibility mirrors
    ffassistant.starters' own rules (a dedicated slot is only "beatable" by
    a benched player at that same position; FLEX by any benched RB/WR/TE;
    SUPER_FLEX by any benched QB/RB/WR/TE). Only the single best-scoring
    eligible bench alternative is reported per starter — not every bench
    player who happened to beat them — sorted worst-gaffe-first by points
    missed.

    This is a direct starter-vs-best-available-benched-alternative
    comparison, not a re-run of the full hindsight-optimal lineup (see
    optimal_lineup_pct) — a real optimal reshuffle can cascade across
    multiple slots at once, which doesn't narrate as cleanly as "you started
    X over Y who was right there on your bench."
    """
    bench = [row for row in team_box_scores if row["slot_name"] == "BENCH"]
    starters = [row for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS]

    gaffes = []
    for starter in starters:
        if starter["slot_name"] in POSITION_SLOTS:
            pool = [b for b in bench if b["position"] == starter["slot_name"]]
        elif starter["slot_name"] == "FLEX":
            pool = [b for b in bench if b["position"] in FLEX_ELIGIBLE]
        elif starter["slot_name"] == "SUPER_FLEX":
            pool = [b for b in bench if b["position"] in SUPERFLEX_ELIGIBLE]
        else:
            pool = []  # unrecognized slot name — nothing to compare against

        better = [b for b in pool if b["points"] > starter["points"]]
        if not better:
            continue
        best_alternative = max(better, key=lambda b: b["points"])
        gaffes.append(
            {
                "team_id": starter["team_id"],
                "slot_name": starter["slot_name"],
                "started": {"player_id": starter["player_id"], "full_name": starter["full_name"], "points": starter["points"]},
                "benched": {
                    "player_id": best_alternative["player_id"],
                    "full_name": best_alternative["full_name"],
                    "points": best_alternative["points"],
                },
                "missed_points": best_alternative["points"] - starter["points"],
            }
        )

    return sorted(gaffes, key=lambda g: g["missed_points"], reverse=True)


def top_players_for_team(team_box_scores: list[dict], limit: int = 3) -> list[dict]:
    """Top-scoring STARTED players for ONE team, best-first — {player_id,
    full_name, position, points} — the "who carried this team" list for a
    single matchup. Unlike top_performers_by_position (league-wide, grouped
    by position), this is scoped to one team and ranks across positions."""
    started = [row for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS]
    players = [
        {"player_id": r["player_id"], "full_name": r["full_name"], "position": r["position"], "points": r["points"]}
        for r in started
    ]
    return sorted(players, key=lambda p: p["points"], reverse=True)[:limit]


def performance_vs_projection(team_box_scores: list[dict], big_game_threshold: float = 5.0) -> list[dict]:
    """STARTED players whose actual points meaningfully beat or missed
    ESPN's pre-game projection — {player_id, full_name, points,
    projected_points, delta, tag: 'over'|'under'}, sorted by the size of the
    surprise (|delta|) descending. The "who had a big game / who cratered"
    signal for a matchup's narrative.

    A row with no projected_points (None) is skipped entirely rather than
    treated as 0 — that would manufacture a fake "huge overperformance" out
    of missing data. big_game_threshold filters out normal week-to-week
    noise; only surprises at least that large are worth narrating.

    This is a projection-delta proxy, not real injury detection — a true
    "left the game hurt" callout would need to cross-reference that week's
    player_status snapshot, which this doesn't do. Flagging that gap rather
    than guessing at it from points alone.
    """
    started = [row for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS]
    results = []
    for row in started:
        projected = row.get("projected_points")
        if projected is None:
            continue
        delta = row["points"] - projected
        if abs(delta) < big_game_threshold:
            continue
        results.append(
            {
                "player_id": row["player_id"],
                "full_name": row["full_name"],
                "points": row["points"],
                "projected_points": projected,
                "delta": delta,
                "tag": "over" if delta > 0 else "under",
            }
        )
    return sorted(results, key=lambda p: abs(p["delta"]), reverse=True)


def matchup_details(matchups: list[dict], box_scores_by_team: dict[int, list[dict]]) -> list[dict]:
    """Enriches matchup_results' output with each side's full story —
    score_by_checkpoint, top_players_for_team, performance_vs_projection —
    everything the recap's per-matchup tab needs. Ordered with the
    closest-margin matchup first (flagged is_matchup_of_the_week — today's
    stand-in for "the matchup worth featuring"), then the rest by ascending
    margin, closest-to-most-lopsided.

    box_scores_by_team is {team_id: [box score rows]} — the same grouping
    gather_recap_data already builds for optimal_lineup_pct/start_sit_gaffes.
    A team_id matchup_results reports that's missing from it (shouldn't
    normally happen, since matchup_results already requires both sides to
    have a scored entry) gets empty detail lists rather than a KeyError.
    """
    def detail(team_id: int) -> dict:
        rows = box_scores_by_team.get(team_id, [])
        return {
            "score_by_checkpoint": score_by_checkpoint(rows),
            "top_players": top_players_for_team(rows),
            "performance_vs_projection": performance_vs_projection(rows),
        }

    ordered = sorted(matchups, key=lambda m: m["margin"])
    return [
        {
            **m,
            "is_matchup_of_the_week": i == 0,
            "team_a_detail": detail(m["team_a"]["team_id"]),
            "team_b_detail": detail(m["team_b"]["team_id"]),
        }
        for i, m in enumerate(ordered)
    ]


def narrative_key(team_a_id: int, team_b_id: int) -> str:
    """Stable string key for one matchup, independent of side order —
    '<lower_id>-<higher_id>' — so a matchup looks the same whether it's read
    as (team_a, team_b) or (team_b, team_a). Used to round-trip hand-written
    narrative text through a JSON file between narrative_brief() and
    apply_narratives() (see those docstrings for the full workflow)."""
    lo, hi = sorted((team_a_id, team_b_id))
    return f"{lo}-{hi}"


def narrative_brief(matchup_details_list: list[dict]) -> list[dict]:
    """Boils matchup_details' output down to just the facts someone needs in
    order to *write* a matchup's Yahoo-recap-style narrative paragraph —
    {'key', 'team_a', 'team_b', 'score_a', 'score_b', 'margin',
    'is_matchup_of_the_week', 'top_players_a', 'top_players_b',
    'surprises_a', 'surprises_b'} — deliberately flat and narrow so the
    writer isn't paging through score_by_checkpoint noise to find the two
    or three things actually worth narrating.

    This is what scripts/prepare_weekly_recap.py dumps to disk as this
    week's "brief": recap_html.py/recap_data.py have no model access, so the
    actual prose has to come from a Claude session reading this brief and
    writing narrative text back into a narratives file — the same "a live
    Claude session does this part, not an API" shape as the Next Week
    Preview's Vegas over/under research. apply_narratives() is the other
    half — it merges that hand-written text back onto matchup_details by
    narrative_key.
    """
    return [
        {
            "key": narrative_key(m["team_a"]["team_id"], m["team_b"]["team_id"]),
            "team_a": m["team_a"]["team_name"],
            "team_b": m["team_b"]["team_name"],
            "score_a": m["team_a"]["points"],
            "score_b": m["team_b"]["points"],
            "margin": m["margin"],
            "is_matchup_of_the_week": m["is_matchup_of_the_week"],
            "top_players_a": m["team_a_detail"]["top_players"],
            "top_players_b": m["team_b_detail"]["top_players"],
            "surprises_a": m["team_a_detail"]["performance_vs_projection"],
            "surprises_b": m["team_b_detail"]["performance_vs_projection"],
        }
        for m in matchup_details_list
    ]


def apply_narratives(matchup_details_list: list[dict], narratives: dict[str, str]) -> list[dict]:
    """Merges hand-written narrative text (keyed by narrative_key — see
    narrative_brief) back onto matchup_details' output, ready for
    recap_html.py to render. A matchup with no matching key (narration
    step skipped, or a matchup added after the brief was written) keeps
    whatever 'narrative' it already had, if any, rather than erroring —
    a recap that's missing one narrative paragraph is a degraded recap,
    not a broken one, so this never blocks the render+send step."""
    return [
        {
            **m,
            "narrative": narratives.get(
                narrative_key(m["team_a"]["team_id"], m["team_b"]["team_id"]), m.get("narrative")
            ),
        }
        for m in matchup_details_list
    ]


STANDING_GAP_CLOSE = 2  # a matchup's two teams count as "close in the standings" if their ranks are within this many spots of each other
PLAYOFF_BUBBLE_LOW, PLAYOFF_BUBBLE_HIGH = 15.0, 85.0  # ESPN playoff_pct band that still counts as genuinely in doubt


def team_standings(teams: list[dict]) -> list[dict]:
    """Ranks teams for the recap's standings table and Next Week Preview —
    input is one dict per team: {team_id, team_name, wins, losses, ties,
    points_for, points_against, playoff_pct, standing}, same shape as
    ffassistant.connectors.espn.get_teams's output (points_for/playoff_pct/
    standing all ESPN-owned, not recomputed here).

    Sorts by ESPN's own `standing` (its tiebreak-resolved playoff seed) and
    attaches a 1-indexed 'rank' reflecting that order — a team synced before
    the standing/playoff_pct columns existed (standing is None) sorts last
    rather than crashing the comparison, since None isn't orderable against
    an int.
    """
    ordered = sorted(teams, key=lambda t: (t["standing"] is None, t["standing"]))
    return [{**t, "rank": i} for i, t in enumerate(ordered, start=1)]


def upcoming_matchup_pairs(matchup_pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Collapses weekly_matchups' both-directions-stored pairs into one
    (team_a_id, team_b_id) tuple per matchup — same de-duplication
    matchup_results does, but for a not-yet-played week that has no scores
    to attach yet (matchup_results requires team_scores for both sides,
    which don't exist until the games are final)."""
    seen = set()
    result = []
    for team_id, opponent_id in matchup_pairs:
        key = tuple(sorted((team_id, opponent_id)))
        if key in seen:
            continue
        seen.add(key)
        result.append((team_id, opponent_id))
    return result


def team_projected_score(team_box_scores: list[dict]) -> float | None:
    """Sums ESPN's own pre-game projected_points across ONE team's currently
    started (non-BENCH/IR) box-score rows for a not-yet-played week — an
    estimate of how that team is expected to score, for the Next Week
    Preview's "shootout" flag. None if none of the started rows have a
    projection yet (nothing synced, or ESPN hasn't produced one); a row
    that's missing its own projection is just skipped rather than treated as
    0, so a partial sync slightly undercounts instead of guessing.
    """
    started = [row for row in team_box_scores if row["slot_name"] not in STARTED_EXCLUDED_SLOTS]
    projections = [row["projected_points"] for row in started if row.get("projected_points") is not None]
    if not projections:
        return None
    return sum(projections)


def next_week_preview(
    standings: list[dict],
    next_week_pairs: list[tuple[int, int]],
    projected_scores: dict[int, float],
    owner_meta: dict[int, dict] | None = None,
) -> list[dict]:
    """Builds the recap's "matchups to watch next week" list — one entry per
    upcoming matchup: {team_a, team_b, tags}, each side carrying its
    standings context (rank/wins/losses/points_for/playoff_pct) plus
    projected_score. `tags` can hold more than one of:

    - 'top_seed_clash': the two teams are #1 and #2 in the standings
    - 'standings_battle': ranks within STANDING_GAP_CLOSE of each other
    - 'playoff_bubble': either side's ESPN playoff_pct is still genuinely in
      doubt (between PLAYOFF_BUBBLE_LOW/HIGH) — not already a lock in or out
    - 'high_scoring': both sides' projected_score is at or above the
      average projected score across every team with one available that
      week — "high" is relative to this league's own scoring settings that
      week, not a fixed number
    - 'sibling_matchup' / 'same_city': from owner_meta (sibling_team_id /
      location) — sprinkled in as a bonus storyline, never required

    A matchup is included even with zero tags (nothing flagged it as
    notable) — the caller decides whether to show only tagged ones or
    everything; sorted most-tagged-first so the standout matchups lead.
    """
    by_team = {s["team_id"]: s for s in standings}
    owner_meta = owner_meta or {}

    available_projections = [v for v in projected_scores.values() if v is not None]
    avg_projection = sum(available_projections) / len(available_projections) if available_projections else None

    results = []
    for team_a_id, team_b_id in next_week_pairs:
        a_stand = by_team.get(team_a_id)
        b_stand = by_team.get(team_b_id)
        tags = []

        a_rank = a_stand["rank"] if a_stand else None
        b_rank = b_stand["rank"] if b_stand else None
        if a_rank is not None and b_rank is not None:
            if {a_rank, b_rank} == {1, 2}:
                tags.append("top_seed_clash")
            elif abs(a_rank - b_rank) <= STANDING_GAP_CLOSE:
                tags.append("standings_battle")

        a_pct = a_stand.get("playoff_pct") if a_stand else None
        b_pct = b_stand.get("playoff_pct") if b_stand else None
        if (a_pct is not None and PLAYOFF_BUBBLE_LOW <= a_pct <= PLAYOFF_BUBBLE_HIGH) or (
            b_pct is not None and PLAYOFF_BUBBLE_LOW <= b_pct <= PLAYOFF_BUBBLE_HIGH
        ):
            tags.append("playoff_bubble")

        a_proj = projected_scores.get(team_a_id)
        b_proj = projected_scores.get(team_b_id)
        if avg_projection is not None and a_proj is not None and b_proj is not None:
            if a_proj >= avg_projection and b_proj >= avg_projection:
                tags.append("high_scoring")

        a_meta = owner_meta.get(team_a_id)
        b_meta = owner_meta.get(team_b_id)
        if a_meta and b_meta:
            if a_meta.get("sibling_team_id") == team_b_id or b_meta.get("sibling_team_id") == team_a_id:
                tags.append("sibling_matchup")
            elif a_meta.get("location") and a_meta["location"] == b_meta.get("location"):
                tags.append("same_city")

        results.append(
            {
                "team_a": {"team_id": team_a_id, **(a_stand or {}), "projected_score": a_proj},
                "team_b": {"team_id": team_b_id, **(b_stand or {}), "projected_score": b_proj},
                "tags": tags,
            }
        )

    return sorted(results, key=lambda m: len(m["tags"]), reverse=True)


def waiver_wire_difference_makers(
    free_agent_scores: list[dict], box_scores: list[dict], limit: int = 5
) -> list[dict]:
    """The week's top-scoring free agents — {player_id, full_name, position,
    points, beat_lowest_starter_at_position, lowest_starter_points} — the
    "you could've picked this guy up" list.

    Each is compared against the lowest score any team actually started at
    that position that week (from box_scores), so "this guy put up 24
    points" comes with a concrete, in-context comparison rather than a bare
    number — lowest_starter_points is None if nobody started that position
    at all. free_agent_scores with an empty/unknown position always get
    lowest_starter_points=None (no fair comparison to make).
    """
    lowest_starter_by_position: dict[str, float] = {}
    for row in box_scores:
        if row["slot_name"] in STARTED_EXCLUDED_SLOTS:
            continue
        position = row["position"]
        if position not in lowest_starter_by_position or row["points"] < lowest_starter_by_position[position]:
            lowest_starter_by_position[position] = row["points"]

    top = sorted(free_agent_scores, key=lambda p: p["points"], reverse=True)[:limit]
    results = []
    for p in top:
        floor = lowest_starter_by_position.get(p["position"])
        results.append(
            {
                "player_id": p["player_id"],
                "full_name": p["full_name"],
                "position": p["position"],
                "points": p["points"],
                "beat_lowest_starter_at_position": floor is not None and p["points"] > floor,
                "lowest_starter_points": floor,
            }
        )
    return results
