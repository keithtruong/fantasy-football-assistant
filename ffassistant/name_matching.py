"""Deterministic player-name matching: exact -> suffix-normalized -> manual override.

Rules-based by design (see CLAUDE.md "Core architecture") — no model calls here.
"""

import re
import sqlite3
from typing import Optional

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize(name: str) -> str:
    """Lowercase, strip periods/commas, drop trailing generational suffixes, collapse whitespace."""
    cleaned = re.sub(r"[.,]", "", name).strip().lower()
    tokens = cleaned.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def match_player(
    conn: sqlite3.Connection,
    source: str,
    raw_name: str,
    position: Optional[str] = None,
) -> Optional[int]:
    """Resolve a raw name from `source` to a canonical player_id, or None if unresolved.

    On failure, records the name in `unresolved_aliases` for manual review
    rather than silently dropping it.
    """
    # 1. Exact match against a previously-resolved alias for this source
    #    (this is also where manual overrides land once recorded).
    row = conn.execute(
        "SELECT player_id FROM player_aliases WHERE source = ? AND alias_name = ?",
        (source, raw_name),
    ).fetchone()
    if row:
        return row["player_id"]

    # 2. Exact match against the canonical name.
    params = [raw_name]
    query = "SELECT player_id FROM players WHERE full_name = ?"
    if position:
        query += " AND position = ?"
        params.append(position)
    rows = conn.execute(query, params).fetchall()
    if len(rows) == 1:
        _record_alias(conn, source, raw_name, rows[0]["player_id"])
        _clear_unresolved(conn, source, raw_name)
        return rows[0]["player_id"]

    # 3. Suffix-normalized match against canonical names.
    normalized_target = normalize(raw_name)
    query = "SELECT player_id, full_name FROM players"
    params = []
    if position:
        query += " WHERE position = ?"
        params.append(position)
    candidates = [
        r for r in conn.execute(query, params).fetchall()
        if normalize(r["full_name"]) == normalized_target
    ]
    if len(candidates) == 1:
        _record_alias(conn, source, raw_name, candidates[0]["player_id"])
        _clear_unresolved(conn, source, raw_name)
        return candidates[0]["player_id"]

    # Unresolved (no match, or an ambiguous multi-match) — queue for manual review.
    conn.execute(
        "INSERT OR IGNORE INTO unresolved_aliases (source, raw_name, position_hint) VALUES (?, ?, ?)",
        (source, raw_name, position),
    )
    conn.commit()
    return None


def resolve_override(conn: sqlite3.Connection, source: str, raw_name: str, player_id: int) -> None:
    """Manually assign an unresolved name to a player_id, clearing it from the review queue."""
    _record_alias(conn, source, raw_name, player_id)
    _clear_unresolved(conn, source, raw_name)
    conn.commit()


def list_unresolved(conn: sqlite3.Connection, source: Optional[str] = None) -> list[sqlite3.Row]:
    if source:
        return conn.execute(
            "SELECT * FROM unresolved_aliases WHERE source = ? ORDER BY first_seen_at", (source,)
        ).fetchall()
    return conn.execute("SELECT * FROM unresolved_aliases ORDER BY first_seen_at").fetchall()


def _record_alias(conn: sqlite3.Connection, source: str, raw_name: str, player_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO player_aliases (player_id, source, alias_name) VALUES (?, ?, ?)",
        (player_id, source, raw_name),
    )
    conn.commit()


def _clear_unresolved(conn: sqlite3.Connection, source: str, raw_name: str) -> None:
    conn.execute(
        "DELETE FROM unresolved_aliases WHERE source = ? AND raw_name = ?",
        (source, raw_name),
    )
