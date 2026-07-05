"""Sync draft rankings (Top-300) and weekly rankings into the database.

Expects `conn` to have `row_factory = sqlite3.Row` (see ffassistant.db.get_connection).

Unlike the platform connectors, a name that fails to match here is NOT auto-created
as a new canonical player — scraped rankings names are less trustworthy than a
platform's structured roster data, so unmatched names stay queued in
unresolved_aliases (via match_player) for manual review instead of being guessed at.
"""

import sqlite3

from ffassistant.connectors import rankings as rankings_api
from ffassistant.name_matching import match_player


def sync_draft_rankings(conn: sqlite3.Connection, season: int, scoring_format: str) -> None:
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
            continue  # queued in unresolved_aliases; skip until manually resolved
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank, adp) "
            "VALUES (?, 'draft', ?, ?, ?, ?)",
            (player_id, season, scoring_format, row["rank"], row["adp"]),
        )
    conn.commit()


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
