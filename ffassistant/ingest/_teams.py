"""Shared helper for the platform ingest modules: cleaning up teams that no
longer appear in a fresh sync (e.g. an owner left and the platform reassigned
that slot's team_id) so they don't accumulate as ghost teams across seasons.
"""

import sqlite3


def remove_stale_teams(conn: sqlite3.Connection, league_id: int, current_platform_team_ids: list[str]) -> None:
    """Deletes team rows for this league whose platform_team_id wasn't in the
    latest sync — but only if no draft picks reference them, so a re-sync can
    never silently destroy real draft-day data.
    """
    placeholders = ",".join("?" for _ in current_platform_team_ids)
    stale = conn.execute(
        f"SELECT team_id FROM teams WHERE league_id = ? AND platform_team_id NOT IN ({placeholders})",
        (league_id, *current_platform_team_ids),
    ).fetchall()

    for row in stale:
        has_picks = conn.execute(
            "SELECT 1 FROM draft_picks WHERE team_id = ? LIMIT 1", (row["team_id"],)
        ).fetchone()
        if has_picks is None:
            conn.execute("DELETE FROM teams WHERE team_id = ?", (row["team_id"],))
