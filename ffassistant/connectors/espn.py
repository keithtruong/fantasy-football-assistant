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
    """One entry per team: platform_team_id, team_name, waiver_priority, and resolved roster players."""
    league = _connect(league_id, year, espn_s2, swid)

    teams = []
    for team in league.teams:
        teams.append(
            {
                "platform_team_id": str(team.team_id),
                "team_name": team.team_name,
                "waiver_priority": team.waiver_rank,
                "players": [
                    {
                        "source_player_id": str(player.playerId),
                        "full_name": player.name,
                        "position": _map_position(player.position),
                        "nfl_team": player.proTeam,
                        "injury_status": player.injuryStatus,
                    }
                    for player in team.roster
                ],
            }
        )
    return teams
