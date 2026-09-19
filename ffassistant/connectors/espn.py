"""Read-only ESPN connector. Requires ESPN_SWID/ESPN_S2 session cookies (see .env / config.py).

Unlike Sleeper, ESPN's League object returns fully-resolved player info (name,
position, pro team, injury status) directly on each team's roster — no separate
player-ID lookup table needed.
"""

from ffassistant.config import ESPN_S2, ESPN_SWID

# ESPN's own slot codes differ from this project's schema vocabulary.
POSITION_MAP = {"D/ST": "DST"}
SLOT_NAME_MAP = {
    "D/ST": "DST",
    "BE": "BENCH",
    "RB/WR": "FLEX",
    "WR/TE": "FLEX",
    "RB/WR/TE": "FLEX",
    "OP": "SUPER_FLEX",
}


def _map_position(espn_position: str | None) -> str | None:
    return POSITION_MAP.get(espn_position, espn_position)


def _roster_status(lineup_slot: str | None) -> str:
    """Collapses ESPN's actual lineupSlot (the real, currently-set lineup
    position — 'BE' for bench, 'IR' for injured reserve, an actual position
    code like 'QB'/'RB/WR/TE' otherwise) down to starter/bench/ir. Feeds the
    Exposure page's Weekly Starters section."""
    if lineup_slot == "BE":
        return "bench"
    if lineup_slot == "IR":
        return "ir"
    return "starter"


def _connect(league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None):
    from espn_api.football import League  # lazy import — optional heavy dependency

    return League(
        league_id=league_id,
        year=year,
        espn_s2=espn_s2 or ESPN_S2,
        swid=swid or ESPN_SWID,
    )


def get_league_settings(
    league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None
) -> dict:
    """Returns {'team_count', 'scoring': {stat_abbr: points}, 'roster_slots': {slot_name: count}}."""
    league = _connect(league_id, year, espn_s2, swid)
    settings = league.settings

    roster_slots: dict[str, int] = {}
    for slot_name, count in settings.position_slot_counts.items():
        if count <= 0:
            continue  # ESPN lists every possible slot type, zeroed out when unused
        mapped = SLOT_NAME_MAP.get(slot_name, slot_name)
        roster_slots[mapped] = roster_slots.get(mapped, 0) + count

    scoring = {item["abbr"]: item["points"] for item in settings.scoring_format if item["points"]}

    return {
        "team_count": settings.team_count,
        "scoring": scoring,
        "roster_slots": roster_slots,
    }


def get_teams(
    league_id: int, year: int, espn_s2: str | None = None, swid: str | None = None
) -> list[dict]:
    """One entry per team: platform_team_id, team_name, waiver_priority,
    wins/losses/ties, points_for/points_against, playoff_pct, standing, and
    resolved roster players.

    playoff_pct is ESPN's own simulation-based playoff-odds percentage for
    that team (their computation, not this project's) — used by the recap's
    Next Week Preview to flag "playoff bubble" matchups without this project
    having to guess a playoff-spot cutoff and recompute tiebreakers itself.
    standing is ESPN's current playoff seed (already tiebreak-resolved), used
    the same way for "close in the standings." Each player's roster_status
    (starter/bench/ir) is ESPN's real, currently-set lineup slot — see
    _roster_status.
    """
    league = _connect(league_id, year, espn_s2, swid)

    teams = []
    for team in league.teams:
        teams.append(
            {
                "platform_team_id": str(team.team_id),
                "team_name": team.team_name,
                "waiver_priority": team.waiver_rank,
                "wins": team.wins,
                "losses": team.losses,
                "ties": team.ties,
                "points_for": team.points_for,
                "points_against": team.points_against,
                "playoff_pct": team.playoff_pct,
                "standing": team.standing,
                "players": [
                    {
                        "source_player_id": str(player.playerId),
                        "full_name": player.name,
                        "position": _map_position(player.position),
                        "nfl_team": player.proTeam,
                        "injury_status": player.injuryStatus,
                        "roster_status": _roster_status(player.lineupSlot),
                    }
                    for player in team.roster
                ],
            }
        )
    return teams


def get_matchups(
    league_id: int, year: int, week: int, espn_s2: str | None = None, swid: str | None = None
) -> list[dict]:
    """This week's opponent pairings, one entry per side: {platform_team_id, opponent_platform_team_id}.
    A bye week (no opponent on one side) is simply omitted rather than paired with a placeholder.
    """
    league = _connect(league_id, year, espn_s2, swid)
    matchups = league.scoreboard(week=week)

    pairs = []
    for matchup in matchups:
        home = getattr(matchup, "home_team", None)
        away = getattr(matchup, "away_team", None)
        if home is None or away is None:
            continue  # bye week — one side has no team to pair with
        pairs.append({"platform_team_id": str(home.team_id), "opponent_platform_team_id": str(away.team_id)})
        pairs.append({"platform_team_id": str(away.team_id), "opponent_platform_team_id": str(home.team_id)})
    return pairs


def _iso_game_date(player) -> str | None:
    """espn_api's BoxPlayer only sets .game_date when it could resolve that
    player's NFL team to a scheduled game that week (a bye week, or a team it
    couldn't match, leaves it unset) — getattr guards both cases."""
    game_date = getattr(player, "game_date", None)
    return game_date.isoformat() if game_date is not None else None


def get_box_scores(
    league_id: int, year: int, week: int, espn_s2: str | None = None, swid: str | None = None
) -> list[dict]:
    """That week's box scores, one entry per team-side of each matchup:
    {platform_team_id, players: [{source_player_id, full_name, position,
    nfl_team, slot_name, points, game_date, projected_points}]}.

    `slot_name` is the *actual* lineup slot the owner started that player in
    that week (mapped through SLOT_NAME_MAP same as get_teams' rosters, so
    'BE' -> 'BENCH', 'RB/WR/TE' -> 'FLEX', etc.) — this is what distinguishes
    a box score from get_teams' current-roster snapshot, and is what lets a
    caller separate "started" from "benched" for that specific week. A bye
    week (one side has no opposing team) still yields that team's own lineup
    entry — a bye doesn't mean the team didn't play its bench/starters that
    week for scoring purposes, it just has no opponent to pair with.

    `game_date` (ISO string, or None if unresolved/bye) is that player's own
    NFL game kickoff time that week — used to reconstruct a retroactive
    "score at each checkpoint" for the recap's per-matchup breakdown.
    `projected_points` is ESPN's own pre-game projection for that player that
    week, used to flag over/under-performances.
    """
    league = _connect(league_id, year, espn_s2, swid)
    box_scores = league.box_scores(week=week)

    entries = []
    for box_score in box_scores:
        for team, lineup in (
            (getattr(box_score, "home_team", None), getattr(box_score, "home_lineup", None)),
            (getattr(box_score, "away_team", None), getattr(box_score, "away_lineup", None)),
        ):
            if team is None or lineup is None:
                continue  # bye week — the empty side of the pairing
            entries.append(
                {
                    "platform_team_id": str(team.team_id),
                    "players": [
                        {
                            "source_player_id": str(player.playerId),
                            "full_name": player.name,
                            "position": _map_position(player.position),
                            "nfl_team": player.proTeam,
                            "slot_name": SLOT_NAME_MAP.get(player.slot_position, player.slot_position),
                            "points": player.points,
                            "game_date": _iso_game_date(player),
                            "projected_points": getattr(player, "projected_points", None),
                        }
                        for player in lineup
                    ],
                }
            )
    return entries


def get_free_agent_scores(
    league_id: int, year: int, week: int, size: int = 300, espn_s2: str | None = None, swid: str | None = None
) -> list[dict]:
    """That week's actual fantasy points for players nobody in the league
    rosters — the "waiver wire" pool — as
    {source_player_id, full_name, position, nfl_team, points, projected_points},
    one entry per free agent/waiver-eligible player.

    espn_api's League.free_agents(week=N) returns the same BoxPlayer wrapper
    get_box_scores' lineups use, with a real per-week .points (pulled from
    that player's own week-N stat entry regardless of roster status) — so,
    contrary to an earlier assumption in this project, box scores aren't the
    only source of real weekly points; free agents carry them too. Same
    wrapper means `projected_points` is available here too — ESPN's own
    pre-game projection, the same field get_box_scores exposes — which is
    what lets the recap's Waiver Wire Watch flag an outlier score relative
    to expectation rather than just whoever scored the most raw points.

    `size` caps how many free agents ESPN returns (sorted by percent-owned,
    most-owned first) — 300 comfortably covers a 12-team league's whole
    unrostered pool without pulling truly replacement-level nobodies.

    Per espn_api's own docs, this "should only be used with most recent
    season" — ESPN doesn't reliably serve a free-agent pool for an old,
    completed season, so unlike get_box_scores this can't be backfilled
    against historical weeks for testing, only exercised live as the current
    season plays out.
    """
    league = _connect(league_id, year, espn_s2, swid)
    free_agents = league.free_agents(week=week, size=size)

    return [
        {
            "source_player_id": str(player.playerId),
            "full_name": player.name,
            "position": _map_position(player.position),
            "nfl_team": player.proTeam,
            "points": player.points,
            "projected_points": getattr(player, "projected_points", None),
        }
        for player in free_agents
    ]
