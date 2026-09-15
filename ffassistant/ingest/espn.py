"""Sync an ESPN league's settings, teams, current rosters, and injury status into the database.

Expects `conn` to have `row_factory = sqlite3.Row` (see ffassistant.db.get_connection).
"""

import sqlite3

from ffassistant.connectors import espn as espn_api
from ffassistant.ingest._teams import remove_stale_teams, resolve_or_create_player, upsert_weekly_matchup
from ffassistant.season import LAST_WEEK

# ESPN's injuryStatus strings, mapped down to this project's player_status enum.
_INJURY_STATUS_MAP = {
    "ACTIVE": "healthy",
    "PROBABLE": "healthy",
    "QUESTIONABLE": "questionable",
    "DOUBTFUL": "questionable",
    "OUT": "out",
    "INJURY_RESERVE": "ir",
    "SUSPENSION": "suspended",
}


def sync_league(
    conn: sqlite3.Connection,
    league_id: int,
    espn_league_id: int,
    year: int,
    week: int | None = None,
) -> None:
    """league_id is this project's internal leagues.league_id; espn_league_id is ESPN's own ID.

    `week` is optional — pass it during an in-season sync to also record each
    player's current injury status for that week; omit it (e.g. draft-day/off-season
    syncs) to sync settings/rosters only.
    """
    _sync_settings(conn, league_id, espn_league_id, year)
    _sync_teams_and_rosters(conn, league_id, espn_league_id, year, week)
    conn.commit()


def _sync_settings(conn: sqlite3.Connection, league_id: int, espn_league_id: int, year: int) -> None:
    settings = espn_api.get_league_settings(espn_league_id, year)

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
    conn: sqlite3.Connection, league_id: int, espn_league_id: int, year: int, week: int | None
) -> None:
    teams = espn_api.get_teams(espn_league_id, year)

    remove_stale_teams(conn, league_id, [team["platform_team_id"] for team in teams])

    team_id_by_platform_id = {}
    for team in teams:
        row = conn.execute(
            "INSERT INTO teams (league_id, platform_team_id, team_name, waiver_priority, wins, losses, ties, "
            "points_for, points_against, playoff_pct, standing) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (league_id, platform_team_id) DO UPDATE SET "
            "team_name = excluded.team_name, waiver_priority = excluded.waiver_priority, "
            "wins = excluded.wins, losses = excluded.losses, ties = excluded.ties, "
            "points_for = excluded.points_for, points_against = excluded.points_against, "
            "playoff_pct = excluded.playoff_pct, standing = excluded.standing "
            "RETURNING team_id",
            (
                league_id,
                team["platform_team_id"],
                team["team_name"],
                team["waiver_priority"],
                team["wins"],
                team["losses"],
                team["ties"],
                team.get("points_for"),
                team.get("points_against"),
                team.get("playoff_pct"),
                team.get("standing"),
            ),
        ).fetchone()
        team_id = row["team_id"]
        team_id_by_platform_id[team["platform_team_id"]] = team_id

        # Full-snapshot sync: replace roster membership rather than diffing,
        # since we don't have transaction history to attribute adds/drops from yet.
        conn.execute("DELETE FROM roster_spots WHERE team_id = ?", (team_id,))
        for player_info in team["players"]:
            player_id = resolve_or_create_player(conn, "espn", player_info)
            conn.execute(
                "INSERT INTO roster_spots (team_id, player_id, acquired_via) VALUES (?, ?, NULL) "
                "ON CONFLICT (team_id, player_id) DO NOTHING",
                (team_id, player_id),
            )
            if week is not None:
                status = _INJURY_STATUS_MAP.get(player_info["injury_status"], "healthy")
                conn.execute(
                    "INSERT INTO player_status (player_id, season, week, status, source) "
                    "VALUES (?, ?, ?, ?, 'espn') "
                    "ON CONFLICT (player_id, season, week) "
                    "DO UPDATE SET status = excluded.status, source = excluded.source",
                    (player_id, year, week, status),
                )

    if week is not None:
        _sync_matchups(conn, league_id, espn_league_id, year, week, team_id_by_platform_id)
        # ESPN publishes the whole regular-season schedule upfront — a
        # matchup pairing isn't something that only becomes knowable once
        # its week "arrives." Syncing next week's pairings too, on every
        # regular refresh, means the recap's Next Week Preview always has
        # them ready by the time it needs them, rather than depending on
        # someone happening to run this again after the current week ends.
        # Cheap and harmless to repeat (full-replace per week, same as the
        # current-week call above) — this doesn't reach past the season.
        if week + 1 <= LAST_WEEK:
            _sync_matchups(conn, league_id, espn_league_id, year, week + 1, team_id_by_platform_id)


def _sync_matchups(conn, league_id, espn_league_id, season, week, team_id_by_platform_id) -> None:
    pairs = espn_api.get_matchups(espn_league_id, season, week)
    conn.execute("DELETE FROM weekly_matchups WHERE league_id = ? AND season = ? AND week = ?", (league_id, season, week))
    for pair in pairs:
        team_id = team_id_by_platform_id.get(pair["platform_team_id"])
        opponent_team_id = team_id_by_platform_id.get(pair["opponent_platform_team_id"])
        if team_id is None or opponent_team_id is None:
            continue
        upsert_weekly_matchup(conn, league_id, season, week, team_id, opponent_team_id)


def sync_box_scores(conn: sqlite3.Connection, league_id: int, espn_league_id: int, season: int, week: int) -> int:
    """Syncs one week's box scores (every rostered player's actual lineup slot
    and points that week, both sides of every matchup including bye weeks)
    into weekly_box_scores — the foundational data behind the weekly recap.

    Unlike sync_league, this isn't part of the regular roster/status refresh
    cadence: a box score only means something once that week's games are
    final, so callers (the recap builder, or a one-off backfill) sync a
    specific already-played week on demand rather than "whatever week is
    current." Full-replace per (league_id, season, week), same convention as
    _sync_matchups above.

    Requires teams to already exist for this league (from a prior sync_league
    call) — a platform_team_id ESPN reports that isn't in the teams table
    yet is skipped rather than guessed at, since a box score alone doesn't
    carry the team_name/waiver_priority a real team row needs.

    Returns the number of player-week rows written, for callers that want to
    report/verify sync results.
    """
    team_id_by_platform_id = {
        row["platform_team_id"]: row["team_id"]
        for row in conn.execute("SELECT platform_team_id, team_id FROM teams WHERE league_id = ?", (league_id,))
    }

    entries = espn_api.get_box_scores(espn_league_id, season, week)

    conn.execute(
        "DELETE FROM weekly_box_scores WHERE league_id = ? AND season = ? AND week = ?", (league_id, season, week)
    )

    written = 0
    for entry in entries:
        team_id = team_id_by_platform_id.get(entry["platform_team_id"])
        if team_id is None:
            continue  # platform reports a team this league's teams table doesn't have yet — skip, don't guess
        for player_info in entry["players"]:
            player_id = resolve_or_create_player(conn, "espn", player_info)
            conn.execute(
                "INSERT INTO weekly_box_scores "
                "(league_id, season, week, team_id, player_id, slot_name, points, game_date, projected_points) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (league_id, season, week, team_id, player_id) "
                "DO UPDATE SET slot_name = excluded.slot_name, points = excluded.points, "
                "game_date = excluded.game_date, projected_points = excluded.projected_points",
                (
                    league_id,
                    season,
                    week,
                    team_id,
                    player_id,
                    player_info["slot_name"],
                    player_info["points"],
                    player_info.get("game_date"),
                    player_info.get("projected_points"),
                ),
            )
            written += 1

    conn.commit()
    return written


def sync_free_agent_scores(
    conn: sqlite3.Connection, league_id: int, espn_league_id: int, season: int, week: int, size: int = 300
) -> int:
    """Syncs one week's free-agent (waiver wire) scores into
    weekly_free_agent_scores — the source behind the recap's Waiver Wire
    Watch. Full-replace per (league_id, season, week), same convention as
    sync_box_scores.

    Unlike sync_box_scores, a free agent has no existing team_id to skip
    against — resolve_or_create_player will create a new players row for
    anyone not already known (a bench-only or truly unrostered player may
    never have appeared in a box score sync yet), which is the right call
    here: these players are exactly the ones worth surfacing as "you could
    have picked this guy up."
    """
    entries = espn_api.get_free_agent_scores(espn_league_id, season, week, size=size)

    conn.execute(
        "DELETE FROM weekly_free_agent_scores WHERE league_id = ? AND season = ? AND week = ?",
        (league_id, season, week),
    )

    written = 0
    for entry in entries:
        player_id = resolve_or_create_player(conn, "espn", entry)
        conn.execute(
            "INSERT INTO weekly_free_agent_scores (league_id, season, week, player_id, points, projected_points) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (league_id, season, week, player_id) "
            "DO UPDATE SET points = excluded.points, projected_points = excluded.projected_points",
            (league_id, season, week, player_id, entry["points"], entry.get("projected_points")),
        )
        written += 1

    conn.commit()
    return written


def sync_weekly_matchups(conn: sqlite3.Connection, league_id: int, espn_league_id: int, season: int, week: int) -> int:
    """Syncs one week's opponent pairings into weekly_matchups on their own,
    independent of a full sync_league roster/settings sync.

    _sync_matchups (above) does the same write, but only as a side effect of
    sync_league — which also re-syncs teams/rosters/injury status for
    whatever `year` you pass it. For a *past* season that's dangerous: ESPN's
    API for an old year returns that year's teams as of query time (often the
    end-of-season roster snapshot), and sync_league would upsert that
    straight over the SAME team_id rows the current season uses, silently
    clobbering this season's live roster/injury data. This function only
    ever touches weekly_matchups, so it's safe to run against a historical
    season/week purely to backfill pairings for recap testing (e.g. TAMS
    2025 week 1) without risking 2026's live data.

    Looks teams up from the DB rather than a live team sync (same convention
    as sync_box_scores) — a platform_team_id this league's teams table
    doesn't have yet is skipped rather than guessed at. Returns the number of
    weekly_matchups rows written (two per real matchup, one per side; a bye
    week contributes zero).
    """
    team_id_by_platform_id = {
        row["platform_team_id"]: row["team_id"]
        for row in conn.execute("SELECT platform_team_id, team_id FROM teams WHERE league_id = ?", (league_id,))
    }

    pairs = espn_api.get_matchups(espn_league_id, season, week)

    conn.execute("DELETE FROM weekly_matchups WHERE league_id = ? AND season = ? AND week = ?", (league_id, season, week))

    written = 0
    for pair in pairs:
        team_id = team_id_by_platform_id.get(pair["platform_team_id"])
        opponent_team_id = team_id_by_platform_id.get(pair["opponent_platform_team_id"])
        if team_id is None or opponent_team_id is None:
            continue
        upsert_weekly_matchup(conn, league_id, season, week, team_id, opponent_team_id)
        written += 1

    conn.commit()
    return written
