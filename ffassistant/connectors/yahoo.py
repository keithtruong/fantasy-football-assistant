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


def _roster_status(selected_position: str | None) -> str:
    """Collapses Yahoo's actual selected_position (the real, currently-set
    lineup position — 'BN' for bench, an 'IR'-prefixed code for injured
    reserve, an actual position/FLEX code otherwise) down to
    starter/bench/ir. Feeds the Exposure page's Weekly Starters section."""
    if selected_position == "BN":
        return "bench"
    if selected_position and selected_position.startswith("IR"):
        return "ir"
    return "starter"


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
    """One entry per team: platform_team_id, team_name, waiver_priority,
    wins/losses/ties, points_for/points_against, and resolved roster players.

    Wins/losses/ties/points_for/points_against aren't in teams()'s own
    metadata — merged in from standings() by team_key, which uses the same
    keys as teams(). A Guillotine-style league's standings entries have no
    "outcome_totals"/"points_against" at all (no head-to-head record to have
    — it's single-elimination-by-lowest-score, not W-L), so those come back
    None there; points_for is still present and used. Each player's
    roster_status (starter/bench/ir) is Yahoo's real, currently-set lineup
    position — see _roster_status.
    """
    league = _connect(league_id, oauth_path)
    teams_meta = league.teams()
    standings_by_team_key = {s["team_key"]: s for s in league.standings()}

    rosters = {team_key: league.to_team(team_key).roster() for team_key in teams_meta}

    all_player_ids = sorted({p["player_id"] for roster in rosters.values() for p in roster})
    nfl_team_by_id = _get_pro_teams(league, all_player_ids)

    teams = []
    for team_key, meta in teams_meta.items():
        standing = standings_by_team_key.get(team_key, {})
        outcomes = standing.get("outcome_totals", {})
        points_for = standing.get("points_for")
        points_against = standing.get("points_against")
        teams.append(
            {
                "platform_team_id": str(meta["team_id"]),
                "team_name": meta["name"],
                "waiver_priority": meta.get("waiver_priority"),
                "wins": int(outcomes["wins"]) if outcomes.get("wins") is not None else None,
                "losses": int(outcomes["losses"]) if outcomes.get("losses") is not None else None,
                "ties": int(outcomes["ties"]) if outcomes.get("ties") is not None else None,
                "points_for": float(points_for) if points_for is not None else None,
                "points_against": float(points_against) if points_against is not None else None,
                "players": [
                    {
                        "source_player_id": str(p["player_id"]),
                        "full_name": p["name"],
                        "position": _map_position(p["eligible_positions"]),
                        "nfl_team": nfl_team_by_id.get(p["player_id"]),
                        "injury_status": _map_status(p["status"]),
                        "roster_status": _roster_status(p.get("selected_position")),
                    }
                    for p in rosters[team_key]
                ],
            }
        )
    return teams


def get_standings(league_id: str, oauth_path=YAHOO_OAUTH_PATH) -> list[dict]:
    """One entry per team: platform_team_id, team_name, points_for -- lighter
    than get_teams() since it skips the per-team roster fetch (18 Team.roster()
    calls) when only the standings numbers are needed, e.g.
    ffassistant.guillotine's weekly cumulative-points-for snapshot.

    points_for here is Yahoo's running season-cumulative total, not a single
    week's score -- see ffassistant.guillotine's module docstring for why a
    single week's score has to be derived as a delta against a prior
    snapshot rather than read directly (Yahoo's own per-week rank_week/
    points_from_chop fields on this same standings() call are live/current-
    week-only, confirmed by inspection).
    """
    league = _connect(league_id, oauth_path)
    return [
        {
            "platform_team_id": s["team_key"].rsplit(".t.", 1)[-1],
            "team_name": s["name"],
            "points_for": float(s["points_for"]),
        }
        for s in league.standings()
    ]


def get_matchups(league_id: str, week: int, oauth_path=YAHOO_OAUTH_PATH) -> list[dict]:
    """This week's opponent pairings, one entry per side: {platform_team_id,
    opponent_platform_team_id, points_for, points_against}.

    league.matchups() only exposes the raw scoreboard response, so this parses it the same
    way get_league_settings() parses raw settings — via objectpath, extracting each
    matchup's pair of team_id values (confirmed by inspection: exactly 2 per matchup;
    a matchup with any other count is skipped rather than guessed at, likely a bye week).

    points_for/points_against come from that same matchup's team_points.total
    (confirmed by inspection against a live league: each has coverage_type
    'week' and appears in the same team order as team_id, so zipping the two
    lists pairs them correctly) — that single week's actual score, NOT the
    same thing as get_teams()'s points_for (season-to-date cumulative).
    Guarded the same way as team_ids: anything other than exactly 2 is
    skipped rather than guessed at.
    """
    import objectpath

    league = _connect(league_id, oauth_path)
    raw = league.matchups(week=week)
    matchups = list(objectpath.Tree(raw).execute("$..matchups"))[0]

    pairs = []
    for key, entry in matchups.items():
        if key == "count":
            continue
        team_ids = list(objectpath.Tree(entry["matchup"]).execute("$..team_id"))
        if len(team_ids) != 2:
            continue
        points = list(objectpath.Tree(entry["matchup"]).execute("$..team_points.total"))
        if len(points) != 2:
            continue
        a, b = team_ids
        pa, pb = float(points[0]), float(points[1])
        pairs.append({"platform_team_id": str(a), "opponent_platform_team_id": str(b), "points_for": pa, "points_against": pb})
        pairs.append({"platform_team_id": str(b), "opponent_platform_team_id": str(a), "points_for": pb, "points_against": pa})
    return pairs


def _get_pro_teams(league, player_ids: list[int]) -> dict[int, str]:
    """Pro-team abbreviation isn't in Team.roster() output; batch-fetch it via player_details()."""
    if not player_ids:
        return {}
    details = league.player_details(player_ids)
    return {int(d["player_id"]): d.get("editorial_team_abbr") for d in details}
