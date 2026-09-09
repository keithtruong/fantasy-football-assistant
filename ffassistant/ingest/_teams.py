"""Shared helpers for the platform ingest modules: cleaning up teams that no
longer appear in a fresh sync (e.g. an owner left and the platform reassigned
that slot's team_id) so they don't accumulate as ghost teams across seasons,
keeping a matched player's NFL team current across resyncs, resolving a
platform roster entry to a canonical player, and recording a week's matchup
pairing.
"""

import sqlite3

from ffassistant.name_matching import match_player, resolve_override
from ffassistant.nfl_teams import canonical_team_code


def resolve_or_create_player(conn: sqlite3.Connection, source: str, player_info: dict) -> int:
    """Resolves a platform roster entry (full_name/position/nfl_team) to a
    canonical player_id via the deterministic name-matching pipeline, or seeds
    a new canonical row on a genuine miss — platform roster data is structured
    (not a scraped name string), so it's safe to treat as authoritative rather
    than parking it in the unresolved-names queue (contrast
    ffassistant.ingest.rankings, which scrapes names and can't trust them the
    same way).

    DST is special-cased: each connector names defenses differently ("DAL
    DST" vs "Dallas Cowboys" vs "Cowboys D/ST" vs Yahoo's bare "Cowboys"), and
    name_matching's exact/suffix-normalized rules don't bridge those styles
    the way they do for person names — left alone, every new naming style
    spawns its own duplicate canonical row (see scripts/dedupe_dst_players.py,
    which mops up existing duplicates). A defense is uniquely identified by
    its NFL team though, so matching on nfl_team first sidesteps the naming
    mismatch entirely instead of creating yet another duplicate.
    """
    nfl_team = canonical_team_code(player_info.get("nfl_team"))
    position = player_info["position"]

    if position == "DST" and nfl_team is not None:
        existing = conn.execute(
            "SELECT player_id FROM players WHERE position = 'DST' AND nfl_team = ?", (nfl_team,)
        ).fetchone()
        if existing is not None:
            resolve_override(conn, source, player_info["full_name"], existing["player_id"])
            return existing["player_id"]

    player_id = match_player(conn, source, player_info["full_name"], position)
    if player_id is not None:
        refresh_nfl_team(conn, player_id, nfl_team)
        return player_id

    cur = conn.execute(
        "INSERT INTO players (full_name, position, nfl_team) VALUES (?, ?, ?)",
        (player_info["full_name"], position, nfl_team),
    )
    player_id = cur.lastrowid
    resolve_override(conn, source, player_info["full_name"], player_id)
    return player_id


def upsert_weekly_matchup(
    conn: sqlite3.Connection, league_id: int, season: int, week: int, team_id: int, opponent_team_id: int
) -> None:
    """A platform can report the same team_id twice for one week (seen on a
    guillotine/elimination-format Yahoo league — the exact shape wasn't
    reproducible offline, but the effect was a crash on weekly_matchups'
    (league_id, season, week, team_id) primary key mid-sync, abandoning that
    league's whole roster refresh). Upserting instead of a bare INSERT means a
    second report for the same team_id just overwrites the first rather than
    taking down the sync.
    """
    conn.execute(
        "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (league_id, season, week, team_id) DO UPDATE SET opponent_team_id = excluded.opponent_team_id",
        (league_id, season, week, team_id, opponent_team_id),
    )


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
