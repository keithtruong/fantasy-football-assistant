"""One-time import of the playoff strength-of-schedule CSV into nfl_team_playoff_sos.

The CSV (data/playoff_sos_2026.csv) is a static, per-season snapshot produced outside
this repo (see DECISIONS.md for the de-vig/implied-win methodology) — this script just
loads it, it doesn't compute anything.

Usage:
    python -m scripts.import_playoff_sos [csv_path] [--season 2026]
"""

import argparse
import csv
import sqlite3
from pathlib import Path

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "playoff_sos_2026.csv"


def import_playoff_sos(csv_path: Path, season: int, conn: sqlite3.Connection | None = None) -> int:
    conn = conn or get_connection()
    conn.execute("DELETE FROM nfl_team_playoff_sos WHERE season = ?", (season,))

    row_count = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                """
                INSERT INTO nfl_team_playoff_sos (
                    season, team, own_implied_wins,
                    wk15_opp, wk15_opp_wins, wk16_opp, wk16_opp_wins, wk17_opp, wk17_opp_wins,
                    playoff_sos_avg_opp_wins, sos_rank
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season,
                    row["team"],
                    float(row["own_implied_wins"]),
                    row["wk15_opp"],
                    float(row["wk15_opp_wins"]),
                    row["wk16_opp"],
                    float(row["wk16_opp_wins"]),
                    row["wk17_opp"],
                    float(row["wk17_opp_wins"]),
                    float(row["playoff_sos_avg_opp_wins"]),
                    int(row["sos_rank_hardest_to_easiest"]),
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

    count = import_playoff_sos(Path(args.csv_path), args.season)
    print(f"Imported {count} teams' playoff SOS for season {args.season}")
