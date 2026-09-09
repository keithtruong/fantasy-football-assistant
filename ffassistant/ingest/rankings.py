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
from ffassistant.nfl_teams import canonical_team_code


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
        (row["full_name"], row["position"], canonical_team_code(row["nfl_team"])),
    )
    player_id = cur.lastrowid
    resolve_override(conn, "rankings_provider", row["full_name"], player_id)
    return player_id


# Beyond the six standard per-position lists, the partner API also exposes two
# cross-position combined lists via these position codes: 'FLX' (RB/WR/TE combined)
# and 'OP' ("offensive player" = QB/RB/WR/TE combined) — the actual data behind a
# FLEX/superflex ranking, since per-position ranks aren't comparable across
# positions. Tagged with list_type so they coexist with the six standard rows
# under the same (player_id, ranking_type, season, week, scoring_format) key
# without colliding — see ffassistant.starters, which is what consumes them.
_WEEKLY_LIST_SPECS = [(p, None) for p in rankings_api.WEEKLY_POSITIONS] + [("FLX", "flex"), ("OP", "superflex")]


def sync_weekly_rankings(conn: sqlite3.Connection, season: int, week: int, scoring_format: str) -> None:
    """scoring_format is one of full_ppr/half_ppr/non_ppr — the partner API has no
    separate superflex-scoring weekly list (only reception scoring varies here), so
    callers should resolve a league's *reception* scoring only
    (ffassistant.api.leagues.derive_reception_scoring), not its full superflex-aware
    scoring_format.
    """
    # Full-snapshot sync: replace this season/week/scoring_format's rankings
    # rather than diffing — scoped by scoring_format too, now that more than
    # one format can coexist for the same season/week. Not scoped by list_type:
    # this call fully owns and repopulates the whole set, standard positions and
    # the two combined lists alike, every time.
    conn.execute(
        "DELETE FROM rankings WHERE ranking_type = 'weekly' AND season = ? AND week = ? AND scoring_format = ?",
        (season, week, scoring_format),
    )

    for position, list_type in _WEEKLY_LIST_SPECS:
        rows = rankings_api.get_weekly_rankings(season, week, position, scoring_format)
        for row in rows:
            player_id = match_player(conn, "rankings_provider", row["full_name"], row["position"])
            if player_id is None:
                continue  # queued in unresolved_aliases; skip until manually resolved
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
                "VALUES (?, 'weekly', ?, ?, ?, ?, ?)",
                (player_id, season, week, scoring_format, row["rank"], list_type),
            )
    conn.commit()


def sync_ros_rankings(conn: sqlite3.Connection, season: int, scoring_format: str) -> None:
    """Rest-of-season rankings: no week (schema convention, same as 'draft'), scraped
    like weekly rankings so a miss is queued for manual review rather than auto-created.
    """
    rows = rankings_api.get_ros_rankings(scoring_format)

    # Full-snapshot sync: replace this season/scoring_format's ROS rankings rather
    # than diffing, since each fetch is a complete refresh.
    conn.execute(
        "DELETE FROM rankings WHERE ranking_type = 'ros' AND season = ? AND scoring_format = ?",
        (season, scoring_format),
    )

    for row in rows:
        player_id = match_player(conn, "rankings_provider", row["full_name"], row["position"])
        if player_id is None:
            continue  # queued in unresolved_aliases; skip until manually resolved
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) "
            "VALUES (?, 'ros', ?, ?, ?)",
            (player_id, season, scoring_format, row["rank"]),
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
