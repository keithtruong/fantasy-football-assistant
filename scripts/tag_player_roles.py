"""Import Keith's own backfield-role calls (bellcow / committee / one-injury-away)
into player_role_tags.

Role assignments are Keith's personal read on each backfield's touch-share
situation — evolving week to week, not a stable fact — so the actual player
list lives in a gitignored JSON snapshot, not hardcoded here, the same
reasoning as the manual sleeper/shy-away notes in import_manual_calls.py.
The file is a JSON object: {"bellcow": [...], "committee": [...],
"one_injury_away": [...]}, each entry a "Player Name (TEAM)" string.

All three roles are RB-specific concepts, so matching is scoped to position
'RB' — tightens the exact/suffix-normalized match against name collisions
with same-named players at other positions.

Usage:
    python -m scripts.tag_player_roles data/player_roles_2026.json
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from ffassistant.db import get_connection
from ffassistant.name_matching import match_player

ROLE_TAGS = ("bellcow", "committee", "one_injury_away")
ROLE_NOTES_SOURCE = "manual_role_notes"

_TRAILING_TEAM_RE = re.compile(r"\s*\(([^)]*)\)\s*$")


def _split_name_and_team(entry: str) -> tuple[str, str | None]:
    match = _TRAILING_TEAM_RE.search(entry)
    if not match:
        return entry.strip(), None
    return entry[: match.start()].strip(), match.group(1).strip().upper()


def tag_player_roles(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    """Upserts player_role_tags from `data` ({tag: ["Player Name (TEAM)", ...]}).

    Returns {"tagged": int, "unresolved": list[str], "team_mismatches": list[str]} —
    `unresolved` holds entries with no confident RB match (queued to unresolved_aliases
    like any other source); `team_mismatches` holds entries whose matched player's
    nfl_team disagrees with the "(TEAM)" hint, worth a manual look even though tagged.
    """
    conn = conn or get_connection()
    tagged = 0
    unresolved = []
    team_mismatches = []

    for tag in ROLE_TAGS:
        for entry in data.get(tag, []):
            name, team_hint = _split_name_and_team(entry)
            player_id = match_player(conn, ROLE_NOTES_SOURCE, name, position="RB")
            if player_id is None:
                unresolved.append(entry)
                continue

            if team_hint:
                row = conn.execute(
                    "SELECT nfl_team FROM players WHERE player_id = ?", (player_id,)
                ).fetchone()
                if row and row["nfl_team"] and row["nfl_team"] != team_hint:
                    team_mismatches.append(f"{entry} matched player_id {player_id} on team {row['nfl_team']}")

            conn.execute(
                """
                INSERT INTO player_role_tags (player_id, tag) VALUES (?, ?)
                ON CONFLICT (player_id) DO UPDATE SET tag = excluded.tag
                """,
                (player_id, tag),
            )
            tagged += 1

    conn.commit()
    return {"tagged": tagged, "unresolved": unresolved, "team_mismatches": team_mismatches}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()

    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    result = tag_player_roles(data)

    if result["unresolved"]:
        print(f"No confident RB match ({len(result['unresolved'])}) — review by hand:")
        for entry in result["unresolved"]:
            print(f"  {entry}")
        print()

    if result["team_mismatches"]:
        print(f"Team mismatches ({len(result['team_mismatches'])}) — verify these matched the right player:")
        for msg in result["team_mismatches"]:
            print(f"  {msg}")
        print()

    print(f"Tagged: {result['tagged']}")
