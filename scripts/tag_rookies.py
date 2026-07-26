"""Rerunnable sync of rookie status onto players.is_rookie.

Sleeper's public player data (see ffassistant/connectors/sleeper.py) carries a
years_exp field per player — 0 means this is that player's first NFL season,
i.e. a rookie. That's used here purely as a source of the rookie fact, not
routed through the exact -> suffix-normalized -> manual-override pipeline in
name_matching.py: that pipeline queues every unresolved name to
unresolved_aliases for manual review, which is right for a real roster/
rankings source but would flood the review queue with thousands of Sleeper's
deep-bench/practice-squad entries this project has no use for. Instead this
matches in the other direction — build a name+position index of Sleeper's
data, then look up each of this project's own (much smaller) players table
rows against it.

DST rows are skipped entirely — "rookie" isn't a meaningful concept for a
team defense.

Usage:
    python -m scripts.tag_rookies
"""

import sqlite3

from ffassistant.connectors.sleeper import get_players_lookup
from ffassistant.db import get_connection
from ffassistant.name_matching import normalize

_ROOKIE_ELIGIBLE_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def _sleeper_rookie_lookup(players_lookup: dict) -> dict[tuple[str, str], bool]:
    """Returns {(normalized_name, position): is_rookie}. Names that collide
    within the same (normalized_name, position) pair are dropped — genuinely
    ambiguous rather than guessed at.
    """
    by_key: dict[tuple[str, str], set[bool]] = {}
    for info in players_lookup.values():
        position = info.get("position")
        if position not in _ROOKIE_ELIGIBLE_POSITIONS:
            continue
        years_exp = info.get("years_exp")
        if years_exp is None:
            continue
        full_name = info.get("full_name") or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
        if not full_name:
            continue
        key = (normalize(full_name), position)
        by_key.setdefault(key, set()).add(years_exp == 0)

    return {key: next(iter(flags)) for key, flags in by_key.items() if len(flags) == 1}


def tag_rookies(conn: sqlite3.Connection | None = None, players_lookup: dict | None = None) -> dict:
    """Sets players.is_rookie from Sleeper's years_exp for every non-DST player
    this project already knows about.

    Returns {"tagged_rookie": int, "tagged_veteran": int, "unmatched": list[str]} —
    `unmatched` holds full_names with no confident Sleeper match, for manual review.
    """
    conn = conn or get_connection()
    players_lookup = players_lookup if players_lookup is not None else get_players_lookup()
    rookie_by_key = _sleeper_rookie_lookup(players_lookup)

    tagged_rookie = 0
    tagged_veteran = 0
    unmatched = []

    rows = conn.execute("SELECT player_id, full_name, position FROM players WHERE position != 'DST'").fetchall()
    for row in rows:
        key = (normalize(row["full_name"]), row["position"])
        if key not in rookie_by_key:
            unmatched.append(row["full_name"])
            continue

        is_rookie = 1 if rookie_by_key[key] else 0
        conn.execute("UPDATE players SET is_rookie = ? WHERE player_id = ?", (is_rookie, row["player_id"]))
        if is_rookie:
            tagged_rookie += 1
        else:
            tagged_veteran += 1

    conn.commit()
    return {"tagged_rookie": tagged_rookie, "tagged_veteran": tagged_veteran, "unmatched": unmatched}


if __name__ == "__main__":
    result = tag_rookies()

    if result["unmatched"]:
        print(f"No confident Sleeper match ({len(result['unmatched'])}) — review by hand:")
        for name in result["unmatched"]:
            print(f"  {name}")
        print()

    print(f"Rookies tagged: {result['tagged_rookie']}")
    print(f"Veterans confirmed: {result['tagged_veteran']}")
