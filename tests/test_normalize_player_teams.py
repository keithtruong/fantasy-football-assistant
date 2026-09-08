import sqlite3
import unittest
from pathlib import Path

from scripts.normalize_player_teams import normalize_player_teams

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestNormalizePlayerTeams(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (?, ?, ?, ?)",
            [
                (1, "Jacory Croskey-Merritt", "RB", "WAS"),
                (2, "Terry McLaurin", "WR", "WSH"),   # already canonical
                (3, "Puka Nacua", "WR", "LA"),
                (4, "Yahoo Guy", "TE", "Bal"),
                (5, "Free Agent", "K", "None"),
                (6, "No Team", "QB", None),
            ],
        )
        self.conn.commit()

    def test_drifted_codes_recoded_and_junk_cleared(self):
        result = normalize_player_teams(conn=self.conn)

        self.assertEqual(result["recoded"], 3)  # WAS, LA, Bal
        self.assertEqual(result["cleared"], 1)  # "None"

        teams = {
            r["player_id"]: r["nfl_team"]
            for r in self.conn.execute("SELECT player_id, nfl_team FROM players")
        }
        self.assertEqual(teams, {1: "WSH", 2: "WSH", 3: "LAR", 4: "BAL", 5: None, 6: None})

    def test_rerun_is_idempotent(self):
        normalize_player_teams(conn=self.conn)
        second = normalize_player_teams(conn=self.conn)
        self.assertEqual(second, {"recoded": 0, "cleared": 0})


if __name__ == "__main__":
    unittest.main()
