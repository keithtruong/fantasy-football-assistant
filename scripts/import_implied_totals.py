"""One-time import of the average-implied-team-total CSV into nfl_team_implied_totals.

The CSV (data/implied_totals_2026.csv) is a static, per-season snapshot produced
outside this repo (see DECISIONS.md for the methodology) — this script just loads
it, it doesn't compute anything.

Usage:
    python -m scripts.import_implied_totals [csv_path] [--season 2026]
"""

import argparse
import csv
import sqlite3
from pathlib import Path

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "implied_totals_2026.csv"


def import_implied_totals(csv_path: Path, season: int, conn: sqlite3.Connection | None = None) -> int:
    conn = conn or get_connection()
    conn.execute("DELETE FROM nfl_team_implied_totals WHERE season = ?", (season,))

    row_count = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                """
                INSERT INTO nfl_team_implied_totals (
                    season, team, implied_tt_full, implied_tt_reg, implied_tt_playoffs, offense_rank
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    season,
                    row["team"],
                    float(row["implied_tt_full"]),
                    float(row["implied_tt_reg"]),
                    float(row["implied_tt_playoffs"]),
                    int(row["offense_rank"]),
                ),
            )
            row_count += 1

    conn.commit()
    return row_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    count = import_implied_totals(Path(args.csv_path), args.season)
    print(f"Imported {count} teams' implied totals for season {args.season}")
