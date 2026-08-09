"""One-time import of the full weeks 1-17 NFL schedule into nfl_team_schedule.

data/nfl_schedule_2026.csv is a static per-season snapshot from the public 2026
schedule release (same source as bye_weeks_2026.csv) — this script just loads
it. Bye weeks aren't included here; see nfl_team_byes for those.

Usage:
    python -m scripts.import_schedule [csv_path] [--season 2026]
"""

import argparse
import csv
import sqlite3
from pathlib import Path

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "nfl_schedule_2026.csv"


def import_schedule(csv_path: Path, season: int, conn: sqlite3.Connection | None = None) -> int:
    conn = conn or get_connection()
    conn.execute("DELETE FROM nfl_team_schedule WHERE season = ?", (season,))

    row_count = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "INSERT INTO nfl_team_schedule (season, team, week, opponent, is_home) VALUES (?, ?, ?, ?, ?)",
                (season, row["team"], int(row["week"]), row["opponent"], int(row["is_home"])),
            )
            row_count += 1

    conn.commit()
    return row_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    count = import_schedule(Path(args.csv_path), args.season)
    print(f"Imported {count} schedule rows for season {args.season}")
