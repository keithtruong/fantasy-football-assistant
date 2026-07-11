"""Sync draft rankings (Top-300) and weekly rankings into the database.

Expects `conn` to have `row_factory = sqlite3.Row` (see ffassistant.db.get_connection).

By default, a name that fails to match here is NOT auto-created as a new canonical
player — scraped rankings names are less trustworthy than a platform's structured
roster data, so unmatched names stay queued in unresolved_aliases (via match_player)
for manual review instead of being guessed at. `sync_draft_rankings` is the one
exception: its `create_missing` flag opts into platform-style auto-creation, since
the Top-300 feed is structured (full_name/position/nfl_team per row) like a roster.
It's meant for the once-a-season preseason bootstrap (see scripts/seed_players_from_rankings.py),
not the routine "Refresh Rankings" sync, which should keep create_missing off.
"""

import sqlite3

from ffassistant.connectors import rankings as rankings_api
from ffassistant.name_matching import match_player, normalize, resolve_override


def sync_draft_rankings(
    conn: sqlite3.Connection, season: int, scoring_format: str, create_missing: bool = False
) -> None:
    rows = rankings_api.get_draft_rankings(scoring_format)

    # Full-snapshot sync: replace this season/scoring_format's rankings rather
    # than diffing, since each fetch is a complete Top-300 refresh.
    conn.execute(
        "DELETE FROM rankings WHERE ranking_type = 'draft' AND season = ? AND scoring_format = ?",
        (season, scoring_format),
    )

    for row in rows:
        player_id = match_player(conn, "rankings_provider", row["full_name"], row["position"])
        if player_id is None:
            if not create_missing or _has_any_candidate(conn, row["full_name"], row["position"]):
                continue  # queued in unresolved_aliases; skip until manually resolved
            player_id = _create_player_from_ranking(conn, row)
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank, adp) "
            "VALUES (?, 'draft', ?, ?, ?, ?)",
            (player_id, season, scoring_format, row["rank"], row["adp"]),
        )
    conn.commit()


def _has_any_candidate(conn: sqlite3.Connection, full_name: str, position) -> bool:
    """True if match_player's miss was an ambiguous multi-match rather than a
    genuine zero-candidate miss — a unique candidate would already have matched,
    so any candidate showing up here means more than one exists."""
    query = "SELECT full_name FROM players"
    params = []
    if position:
        query += " WHERE position = ?"
        params.append(position)
    candidates = conn.execute(query, params).fetchall()
    normalized_target = normalize(full_name)
    return any(normalize(r["full_name"]) == normalized_target for r in candidates)


def _create_player_from_ranking(conn: sqlite3.Connection, row) -> int:
    cur = conn.execute(
        "INSERT INTO players (full_name, position, nfl_team) VALUES (?, ?, ?)",
        (row["full_name"], row["position"], row["nfl_team"]),
    )
    player_id = cur.lastrowid
    resolve_override(conn, "rankings_provider", row["full_name"], player_id)
    return player_id


def sync_weekly_rankings(conn: sqlite3.Connection, season: int, week: int) -> None:
    # Full-snapshot sync: replace this season/week's rankings rather than diffing.
    conn.execute(
        "DELETE FROM rankings WHERE ranking_type = 'weekly' AND season = ? AND week = ?",
        (season, week),
    )

    for position in rankings_api.WEEKLY_POSITIONS:
        rows = rankings_api.get_weekly_rankings(season, week, position)
        for row in rows:
            player_id = match_player(conn, "rankings_provider", row["full_name"], row["position"])
            if player_id is None:
                continue  # queued in unresolved_aliases; skip until manually resolved
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank) "
                "VALUES (?, 'weekly', ?, ?, 'half_ppr', ?)",
                (player_id, season, week, row["rank"]),
            )
    conn.commit()


def sync_tiers(conn: sqlite3.Connection, season: int) -> None:
    """Tier is scoring-format-invariant, so this updates every scoring_format row
    already ingested for that player/season's draft rankings — not a separate insert.
    """
    for position in rankings_api.TIER_POSITIONS:
        rows = rankings_api.get_tiers(position)
        for row in rows:
            player_id = match_player(conn, "rankings_provider", row["full_name"], position)
            if player_id is None:
                continue  # queued in unresolved_aliases; skip until manually resolved
            conn.execute(
                "UPDATE rankings SET tier = ? WHERE player_id = ? AND ranking_type = 'draft' AND season = ?",
                (row["tier"], player_id, season),
            )
    conn.commit()
