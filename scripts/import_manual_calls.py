"""One-time import of Keith's sleeper/shy-away player calls from manual
player-call notes into player_manual_tags.

These notes are paraphrased research pulled by hand from outside draft-prep
content (never named here or anywhere committed — see CLAUDE.md's
confidentiality rule) into a gitignored markdown file, grouped by team. Each
line looks like:

    - Player Name — VERDICT — ~12:34 — one-sentence reason.

where VERDICT is some form of SLEEPER or SHY-AWAY. Lines whose verdict is
marked "mixed", "split opinion", or otherwise carries both/neither signal are
skipped and printed for manual review rather than guessed at.

Usage:
    python -m scripts.import_manual_calls notes/some-notes-file.md
"""

import argparse
import re
import sqlite3
from pathlib import Path

from ffassistant.db import get_connection
from ffassistant.name_matching import match_player

# Generic per CLAUDE.md's confidentiality rule — never the actual source name.
MANUAL_NOTES_SOURCE = "manual_player_notes"

_TEAM_HEADER_RE = re.compile(r"^\*\*(.+)\*\*$")
_BULLET_RE = re.compile(r"^-\s+(.*)$")
_TRAILING_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")
_POSITIONS = {"QB", "RB", "WR", "TE", "DST", "K"}


def _classify_verdict(verdict_text: str) -> str | None:
    """Return 'sleeper', 'shy_away', or None if the verdict is ambiguous."""
    text = verdict_text.upper()
    if "MIXED" in text or "SPLIT" in text:
        return None
    has_sleeper = "SLEEPER" in text
    has_shy_away = "SHY-AWAY" in text or "SHY AWAY" in text
    if has_sleeper and has_shy_away:
        return None
    if has_sleeper:
        return "sleeper"
    if has_shy_away:
        return "shy_away"
    return None


def _strip_qualifier(name: str) -> str:
    """Drop a trailing parenthetical like "(rookie WR)" or "(TE)" — not part
    of the player's actual name.
    """
    return _TRAILING_QUALIFIER_RE.sub("", name).strip()


def _extract_position_hint(name: str) -> str | None:
    match = re.search(r"\(([^)]*)\)\s*$", name)
    if not match:
        return None
    for token in re.split(r"[\s/]+", match.group(1).upper()):
        if token in _POSITIONS:
            return token
    return None


def _iter_calls(text: str):
    """Yield (team, name, verdict_text, raw_line) for each bullet-list call line."""
    team = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        team_match = _TEAM_HEADER_RE.match(line)
        if team_match:
            team = team_match.group(1)
            continue
        bullet_match = _BULLET_RE.match(line)
        if not bullet_match:
            continue
        parts = re.split(r"\s+—\s+", bullet_match.group(1), maxsplit=3)
        if len(parts) < 3:
            yield team, None, None, raw_line.strip()
            continue
        name, verdict_text = parts[0], parts[1]
        yield team, name.strip(), verdict_text.strip(), raw_line.strip()


def import_manual_calls(md_path: Path, conn: sqlite3.Connection | None = None) -> dict:
    """Parse `md_path` and upsert player_manual_tags for every clear-verdict line.

    Returns {"tagged": int, "unresolved": int, "skipped": list[str]} — `skipped`
    holds the raw source lines for ambiguous or unparsable calls, for manual review.
    """
    conn = conn or get_connection()
    text = md_path.read_text(encoding="utf-8")

    tagged = 0
    unresolved = 0
    skipped = []

    for _team, name, verdict_text, raw_line in _iter_calls(text):
        if name is None:
            skipped.append(raw_line)
            continue

        tag = _classify_verdict(verdict_text)
        if tag is None:
            skipped.append(raw_line)
            continue

        clean_name = _strip_qualifier(name)
        position_hint = _extract_position_hint(name)
        player_id = match_player(conn, MANUAL_NOTES_SOURCE, clean_name, position=position_hint)

        if player_id is None:
            unresolved += 1
            continue

        conn.execute(
            """
            INSERT INTO player_manual_tags (player_id, tag) VALUES (?, ?)
            ON CONFLICT (player_id) DO UPDATE SET tag = excluded.tag
            """,
            (player_id, tag),
        )
        tagged += 1

    conn.commit()
    return {"tagged": tagged, "unresolved": unresolved, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("md_path", type=Path)
    args = parser.parse_args()

    result = import_manual_calls(args.md_path)

    if result["skipped"]:
        print(f"Skipped {len(result['skipped'])} ambiguous/unparsable line(s) — review by hand:")
        for line in result["skipped"]:
            print(f"  {line}")
        print()

    print(f"Tags set: {result['tagged']}")
    print(f"Sent to unresolved_aliases (no confident player match): {result['unresolved']}")
    print(f"Skipped as ambiguous/unparsable: {len(result['skipped'])}")
