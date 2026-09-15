"""One-off diagnostic: checks whether data/ffassistant.db is readable and
free of a stuck rollback journal.

Why this exists: a sync run through the Claude Cowork device link hit a
"disk I/O error" mid-write and left behind a data/ffassistant.db-journal
file that even a plain read couldn't clear — consistent with the connected
folder's network mount not fully supporting the file-locking behavior
SQLite (and, separately, git) need. Opening the same database file
natively (this script, run directly on the machine rather than through
that mount) either clears the stuck journal on its own — SQLite
auto-rolls-back a leftover journal the moment a normal, unmounted
connection opens the file — or confirms the problem is something other
than the mount.

Read-only: only ever runs PRAGMA integrity_check, never writes.

Usage (from a command prompt, in this folder):
    python -m scripts.check_db_health
"""

import sqlite3
import sys
from pathlib import Path

from ffassistant.config import DB_PATH


def main() -> int:
    journal_path = Path(str(DB_PATH) + "-journal")

    print(f"Database file: {DB_PATH}")
    print(f"Stray journal file present before check: {journal_path.exists()}")
    print()

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
    except sqlite3.Error as e:
        print(f"FAILED to open/read the database: {e}")
        print("This means the problem is not just the Claude folder mount — something else is wrong.")
        return 1

    print(f"integrity_check result: {result[0]}")
    print(f"Stray journal file present after check: {journal_path.exists()}")
    print()

    if result[0] == "ok":
        print("Database is healthy and readable. If the journal file is now gone, the stuck-journal")
        print("issue is cleared — the Claude session can go back to using it through the folder link.")
        return 0
    else:
        print("Database opened, but integrity_check reported a problem (see above) — worth flagging")
        print("this exact output before doing anything else to the file.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
