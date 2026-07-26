import sqlite3
import unittest
from pathlib import Path

from scripts.tag_rookies import tag_rookies

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def sleeper_player(full_name, position, years_exp):
    return {"full_name": full_name, "position": position, "years_exp": years_exp}


class TestTagRookies(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position) VALUES (?, ?, ?)",
            [
                (1, "Brand New Rookie", "WR"),
                (2, "Josh Allen", "QB"),
                (3, "Some Vet Jr.", "RB"),
                (4, "ATL DST", "DST"),
                (5, "No Sleeper Match", "TE"),
            ],
        )
        self.conn.commit()

        self.players_lookup = {
            "1001": sleeper_player("Brand New Rookie", "WR", 0),
            "1002": sleeper_player("Josh Allen", "QB", 7),
            "1003": sleeper_player("Some Vet", "RB", 3),  # Jr./Sr. dropped by normalize()
        }

    def test_rookie_flagged_from_zero_years_exp(self):
        tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 1").fetchone()
        self.assertEqual(row["is_rookie"], 1)

    def test_veteran_flagged_false(self):
        tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 2").fetchone()
        self.assertEqual(row["is_rookie"], 0)

    def test_suffix_normalized_match(self):
        tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 3").fetchone()
        self.assertEqual(row["is_rookie"], 0)

    def test_dst_rows_are_skipped_entirely(self):
        result = tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        self.assertNotIn("ATL DST", result["unmatched"])
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 4").fetchone()
        self.assertEqual(row["is_rookie"], 0)

    def test_unmatched_player_reported_and_left_untouched(self):
        result = tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        self.assertIn("No Sleeper Match", result["unmatched"])
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 5").fetchone()
        self.assertEqual(row["is_rookie"], 0)

    def test_ambiguous_sleeper_name_collision_is_not_guessed_at(self):
        # Two different real players share a normalized name/position in Sleeper's
        # data, one a rookie and one not — genuinely ambiguous, so left unmatched.
        players_lookup = dict(self.players_lookup)
        players_lookup["1004"] = sleeper_player("Brand New Rookie", "WR", 5)

        result = tag_rookies(conn=self.conn, players_lookup=players_lookup)

        self.assertIn("Brand New Rookie", result["unmatched"])
        row = self.conn.execute("SELECT is_rookie FROM players WHERE player_id = 1").fetchone()
        self.assertEqual(row["is_rookie"], 0)

    def test_counts_returned(self):
        result = tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        self.assertEqual(result["tagged_rookie"], 1)
        self.assertEqual(result["tagged_veteran"], 2)
        self.assertEqual(len(result["unmatched"]), 1)

    def test_rerun_is_idempotent(self):
        tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        second = tag_rookies(conn=self.conn, players_lookup=self.players_lookup)
        self.assertEqual(second["tagged_rookie"], 1)
        self.assertEqual(second["tagged_veteran"], 2)


if __name__ == "__main__":
    unittest.main()
