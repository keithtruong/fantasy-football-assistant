"""One-off fix: corrects team_id=120's display_name from ESPN's raw
placeholder "JFN" to the real, safe-to-publish nickname "Johnny", per
Keith's stated owner name/nickname list (John/Johnny) and the exact
example already called out in ffassistant/recap_data.py's own docstring
("owners.display_nickname ... e.g. 'Johnny', never ESPN's 'JFN'").

Run natively (not through the Claude Cowork device link/mounted folder) —
the mounted folder doesn't reliably support SQLite's file-locking during a
write and can leave a stuck rollback journal (see scripts/check_db_health.py
and CLAUDE.md's "Network access from Claude sandboxes" section for the full
story). This script also runs the same integrity/stuck-journal check first,
so it doubles as recovery if a prior write attempt left a stray journal.

Usage (from a command prompt, in this folder):
    python -m scripts.fix_owner_nickname
"""

import sqlite3
import sys
from pathlib import Path

from ffassistant.config import DB_PATH

TEAM_ID = 120
OLD_NAME = "JFN"
NEW_NAME = "Johnny"


def main() -> int:
    journal_path = Path(str(DB_PATH) + "-journal")

    print(f"Database file: {DB_PATH}")
    print(f"Stray journal file present before check: {journal_path.exists()}")
    print()

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        result = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as e:
        print(f"FAILED to open the database: {e}")
        print("This means the problem is not just the Claude folder mount — something else is wrong.")
        return 1

    print(f"integrity_check result: {result[0]}")
    if result[0] != "ok":
        print("Database opened, but integrity_check reported a problem — stopping before making any changes.")
        conn.close()
        return 1

    row = conn.execute("SELECT display_name FROM teams WHERE team_id = ?", (TEAM_ID,)).fetchone()
    if row is None:
        print(f"No team found with team_id={TEAM_ID} — nothing to fix.")
        conn.close()
        return 1

    current_name = row[0]
    print(f"Team {TEAM_ID} current display_name: {current_name!r}")

    if current_name != OLD_NAME:
        print(f"display_name is not {OLD_NAME!r} (already changed, or this script is stale) — leaving it alone.")
        conn.close()
        return 0

    conn.execute("UPDATE teams SET display_name = ? WHERE team_id = ?", (NEW_NAME, TEAM_ID))
    conn.commit()

    row = conn.execute("SELECT display_name FROM teams WHERE team_id = ?", (TEAM_ID,)).fetchone()
    conn.close()

    print(f"Team {TEAM_ID} display_name is now: {row[0]!r}")
    print(f"Stray journal file present after write: {journal_path.exists()}")

    if row[0] == NEW_NAME:
        print()
        print("Fix applied successfully. The Claude session can now regenerate the weekly")
        print("recaps and they'll show 'Johnny' instead of 'JFN' going forward.")
        return 0
    else:
        print("Something went wrong — display_name did not update as expected.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
