"""Read-only Yahoo connector. Requires .yahoo_oauth.json (see config.py) with valid OAuth2 tokens.

Only ever call read-only yahoo_fantasy_api methods here (teams(), settings(), positions(),
Team.roster(), player_details(), Game.league_ids()) — this project never writes back to any
platform, and yahoo_fantasy_api's Team object also exposes add_player/drop_player/
change_positions/propose_trade, which must never be called from this codebase.
"""

import re

from ffassistant.config import YAHOO_OAUTH_PATH

# Yahoo's own slot/status codes differ from this project's schema vocabulary.
SLOT_NAME_MAP = {
    "DEF": "DST",
    "BN": "BENCH",
    "W/R/T": "FLEX",
    "Q/W/R/T": "SUPER_FLEX",
}

_STATUS_MAP = {
    "": "healthy",
    "Q": "questionable",
    "D": "questionable",
    "O": "out",
    "IR": "ir",
    "PUP": "ir",
    "SUSP": "suspended",
}


def _slugify(display_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")


def _map_position(eligible_positions: list[str]) -> str | None:
    if not eligible_positions:
        return None
    primary = eligible_positions[0]
    return "DST" if primary == "DEF" else primary


def _map_status(status: str) -> str:
    return _STATUS_MAP.get(status, "questionable" if status else "healthy")


def _connect_game(oauth_path=YAHOO_OAUTH_PATH):
    from yahoo_oauth import OAuth2  # lazy import — optional heavy dependency
    import yahoo_fantasy_api as yfa

    sc = OAuth2(None, None, from_file=str(oauth_path))
    return yfa.Game(sc, "nfl")


def _connect(league_id: str, oauth_path=YAHOO_OAUTH_PATH):
    return _connect_game(oauth_path).to_league(league_id)


def list_league_ids(season: int | None = None, oauth_path=YAHOO_OAUTH_PATH) -> list[str]:
    """Returns this account's Yahoo league keys, e.g. '470.l.150416'.

    Yahoo league keys are `{game_key}.l.{league_id}`, and game_key changes every season —
    the bare numeric ID in a Yahoo league URL is only the league_id portion. Pass `season`
    to filter to one year's leagues; omit it to list every season on record.
    """
    return _connect_game(oauth_path).league_ids(year=season)


def get_league_settings(league_id: str, oauth_path=YAHOO_OAUTH_PATH) -> dict:
    """Returns {'team_count', 'scoring': {stat_key: points}, 'roster_slots': {slot_name: count}}.

    yahoo_fantasy_api's own settings()/stat_categories() wrappers don't expose per-stat
    point values, so scoring is built from the raw settings response's stat_modifiers
    (stat_id -> value) matched against stat_categories (stat_id -> display_name).
    """
    import objectpath

    league = _connect(league_id, oauth_path)
    settings = league.settings()

    roster_slots: dict[str, int] = {}
    for slot_name, info in league.positions().items():
        mapped = SLOT_NAME_MAP.get(slot_name, slot_name)
        roster_slots[mapped] = roster_slots.get(mapped, 0) + int(info["count"])

    raw = league.yhandler.get_settings_raw(league.league_id)
    stat_names = {
        c["stat_id"]: c["display_name"] for c in objectpath.Tree(raw).execute("$..stat_categories..stat")
    }

    scoring = {}
    for entry in settings.get("stat_modifiers", {}).get("stats", []):
        stat = entry["stat"]
        name = stat_names.get(stat["stat_id"])
        if name:
            scoring[_slugify(name)] = float(stat["value"])

    return {
        "team_count": int(settings["num_teams"]),
        "scoring": scoring,
        "roster_slots": roster_slots,
    }


def get_teams(league_id: str, oauth_path=YAHOO_OAUTH_PATH) -> list[dict]:
    """One entry per team: platform_team_id, team_name, waiver_priority, and resolved roster players."""
    league = _connect(league_id, oauth_path)
    teams_meta = league.teams()

    rosters = {team_key: league.to_team(team_key).roster() for team_key in teams_meta}

    all_player_ids = sorted({p["player_id"] for roster in rosters.values() for p in roster})
    nfl_team_by_id = _get_pro_teams(league, all_player_ids)

    teams = []
    for team_key, meta in teams_meta.items():
        teams.append(
            {
                "platform_team_id": str(meta["team_id"]),
                "team_name": meta["name"],
                "waiver_priority": meta.get("waiver_priority"),
                "players": [
                    {
                        "source_player_id": str(p["player_id"]),
                        "full_name": p["name"],
                        "position": _map_position(p["eligible_positions"]),
                        "nfl_team": nfl_team_by_id.get(p["player_id"]),
                        "injury_status": _map_status(p["status"]),
                    }
                    for p in rosters[team_key]
                ],
            }
        )
    return teams


def _get_pro_teams(league, player_ids: list[int]) -> dict[int, str]:
    """Pro-team abbreviation isn't in Team.roster() output; batch-fetch it via player_details()."""
    if not player_ids:
        return {}
    details = league.player_details(player_ids)
    return {int(d["player_id"]): d.get("editorial_team_abbr") for d in details}
