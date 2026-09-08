"""Sync a Sleeper league's settings, teams, current rosters, and injury status into the database.

Expects `conn` to have `row_factory = sqlite3.Row` (see ffassistant.db.get_connection).
"""

import sqlite3

from ffassistant.connectors import sleeper as sleeper_api
from ffassistant.ingest._teams import refresh_nfl_team, remove_stale_teams
from ffassistant.name_matching import match_player, resolve_override
from ffassistant.nfl_teams import canonical_team_code

# Sleeper's own injuryStatus strings, mapped down to this project's player_status enum.
_INJURY_STATUS_MAP = {
    "Questionable": "questionable",
    "Doubtful": "questionable",
    "Out": "out",
    "IR": "ir",
    "PUP": "ir",
    "Sus": "suspended",
    "COV": "out",
    "DNR": "out",
    "NA": "out",
}


def sync_league(
    conn: sqlite3.Connection,
    league_id: int,
    sleeper_league_id: str,
    season: int | None = None,
    week: int | None = None,
) -> None:
    """league_id is this project's internal leagues.league_id; sleeper_league_id is Sleeper's own ID.

    `week` is optional — pass it (with `season`) during an in-season sync to also
    record each player's current injury status for that week.
    """
    _sync_settings(conn, league_id, sleeper_league_id)
    _sync_teams_and_rosters(conn, league_id, sleeper_league_id, season, week)
    conn.commit()


def _sync_settings(conn: sqlite3.Connection, league_id: int, sleeper_league_id: str) -> None:
    settings = sleeper_api.get_league_settings(sleeper_league_id)

    for stat_key, points in settings["scoring"].items():
        conn.execute(
            "INSERT INTO league_scoring (league_id, stat_key, points) VALUES (?, ?, ?) "
            "ON CONFLICT (league_id, stat_key) DO UPDATE SET points = excluded.points",
            (league_id, stat_key, points),
        )

    for slot_name, count in settings["roster_slots"].items():
        conn.execute(
            "INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (?, ?, ?) "
            "ON CONFLICT (league_id, slot_name) DO UPDATE SET slot_count = excluded.slot_count",
            (league_id, slot_name, count),
        )


def _sync_teams_and_rosters(
    conn: sqlite3.Connection,
    league_id: int,
    sleeper_league_id: str,
    season: int | None,
    week: int | None,
) -> None:
    teams = sleeper_api.get_teams(sleeper_league_id)
    players_lookup = sleeper_api.get_players_lookup()

    remove_stale_teams(conn, league_id, [team["platform_team_id"] for team in teams])

    team_id_by_platform_id = {}
    for team in teams:
        row = conn.execute(
            "INSERT INTO teams (league_id, platform_team_id, team_name, waiver_priority, wins, losses, ties) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (league_id, platform_team_id) DO UPDATE SET "
            "team_name = excluded.team_name, waiver_priority = excluded.waiver_priority, "
            "wins = excluded.wins, losses = excluded.losses, ties = excluded.ties "
            "RETURNING team_id",
            (
                league_id,
                team["platform_team_id"],
                team["team_name"],
                team["waiver_priority"],
                team["wins"],
                team["losses"],
                team["ties"],
            ),
        ).fetchone()
        team_id = row["team_id"]
        team_id_by_platform_id[team["platform_team_id"]] = team_id

        # Full-snapshot sync: replace roster membership rather than diffing,
        # since we don't have transaction history to attribute adds/drops from yet.
        conn.execute("DELETE FROM roster_spots WHERE team_id = ?", (team_id,))
        for player_info in sleeper_api.get_roster_players(team["player_ids"], players_lookup):
            player_id = _resolve_or_create_player(conn, player_info)
            conn.execute(
                "INSERT INTO roster_spots (team_id, player_id, acquired_via) VALUES (?, ?, NULL) "
                "ON CONFLICT (team_id, player_id) DO NOTHING",
                (team_id, player_id),
            )
            if week is not None:
                status = _INJURY_STATUS_MAP.get(player_info["injury_status"], "healthy")
                conn.execute(
                    "INSERT INTO player_status (player_id, season, week, status, source) "
                    "VALUES (?, ?, ?, ?, 'sleeper') "
                    "ON CONFLICT (player_id, season, week) "
                    "DO UPDATE SET status = excluded.status, source = excluded.source",
                    (player_id, season, week, status),
                )

    if week is not None:
        _sync_matchups(conn, league_id, sleeper_league_id, season, week, team_id_by_platform_id)


def _sync_matchups(conn, league_id, sleeper_league_id, season, week, team_id_by_platform_id) -> None:
    pairs = sleeper_api.get_matchups(sleeper_league_id, week)
    conn.execute("DELETE FROM weekly_matchups WHERE league_id = ? AND season = ? AND week = ?", (league_id, season, week))
    for pair in pairs:
        team_id = team_id_by_platform_id.get(pair["platform_team_id"])
        opponent_team_id = team_id_by_platform_id.get(pair["opponent_platform_team_id"])
        if team_id is None or opponent_team_id is None:
            continue
        conn.execute(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (?, ?, ?, ?, ?)",
            (league_id, season, week, team_id, opponent_team_id),
        )


def _resolve_or_create_player(conn: sqlite3.Connection, player_info: dict) -> int:
    nfl_team = canonical_team_code(player_info.get("nfl_team"))
    player_id = match_player(conn, "sleeper", player_info["full_name"], player_info["position"])
    if player_id is not None:
        refresh_nfl_team(conn, player_id, nfl_team)
        return player_id

    # Sleeper's player data is structured (not a scraped name string), so on a genuine
    # miss it's safe to treat it as authoritative and seed a new canonical player
    # rather than leaving it stuck in the unresolved-names queue.
    cur = conn.execute(
        "INSERT INTO players (full_name, position, nfl_team) VALUES (?, ?, ?)",
        (player_info["full_name"], player_info["position"], nfl_team),
    )
    player_id = cur.lastrowid
    resolve_override(conn, "sleeper", player_info["full_name"], player_id)
    return player_id
