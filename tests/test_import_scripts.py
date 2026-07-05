import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_byes import import_byes
from scripts.import_playoff_sos import import_playoff_sos

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestImportPlayoffSos(unittest.TestCase):
    def test_imports_rows_and_is_idempotent_on_resync(self):
        conn = make_conn()
        csv_content = (
            "sos_rank_hardest_to_easiest,team,team_name,own_implied_wins,"
            "wk15_opp,wk15_opp_wins,wk16_opp,wk16_opp_wins,wk17_opp,wk17_opp_wins,"
            "playoff_sos_avg_opp_wins\n"
            "1,CHI,Chicago Bears,9.285,BUF,10.801,GB,9.908,DET,10.812,10.507\n"
            "32,ARI,Arizona Cardinals,3.908,NYJ,5.609,NO,7.663,LV,5.961,6.411\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "sos.csv"
            csv_path.write_text(csv_content)

            count = import_playoff_sos(csv_path, season=2026, conn=conn)
            self.assertEqual(count, 2)

            row = conn.execute(
                "SELECT * FROM nfl_team_playoff_sos WHERE team = 'CHI'"
            ).fetchone()
            self.assertEqual(row["sos_rank"], 1)
            self.assertEqual(row["wk15_opp"], "BUF")
            self.assertEqual(row["playoff_sos_avg_opp_wins"], 10.507)

            # Re-import should replace, not duplicate.
            import_playoff_sos(csv_path, season=2026, conn=conn)
            total = conn.execute("SELECT COUNT(*) AS c FROM nfl_team_playoff_sos").fetchone()["c"]
            self.assertEqual(total, 2)


class TestImportByes(unittest.TestCase):
    def test_imports_rows_and_is_idempotent_on_resync(self):
        conn = make_conn()
        csv_content = "team,bye_week\nCAR,5\nKC,5\nDAL,14\n"
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "byes.csv"
            csv_path.write_text(csv_content)

            count = import_byes(csv_path, season=2026, conn=conn)
            self.assertEqual(count, 3)

            row = conn.execute("SELECT bye_week FROM nfl_team_byes WHERE team = 'DAL'").fetchone()
            self.assertEqual(row["bye_week"], 14)

            import_byes(csv_path, season=2026, conn=conn)
            total = conn.execute("SELECT COUNT(*) AS c FROM nfl_team_byes").fetchone()["c"]
            self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
