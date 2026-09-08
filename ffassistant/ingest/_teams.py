"""Shared helpers for the platform ingest modules: cleaning up teams that no
longer appear in a fresh sync (e.g. an owner left and the platform reassigned
that slot's team_id) so they don't accumulate as ghost teams across seasons,
and keeping a matched player's NFL team current across resyncs.
"""

import sqlite3


def refresh_nfl_team(conn: sqlite3.Connection, player_id: int, nfl_team: str | None) -> None:
    """Update players.nfl_team from a platform resync when it has actually changed.

    nfl_team is set at player creation but otherwise never revisited, so a
    traded/signed player kept his old team until now (and, historically, the
    first source to create the row also locked in its team-code spelling —
    see ffassistant.nfl_teams). Pass the already-canonicalized code; a None
    (free agent / missing) is ignored rather than blanking a known team, since
    platform roster data drops players the moment they're cut anyway.
    """
    if nfl_team is None:
        return
    conn.execute(
        "UPDATE players SET nfl_team = ? WHERE player_id = ? AND (nfl_team IS NULL OR nfl_team != ?)",
        (nfl_team, player_id, nfl_team),
    )


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
