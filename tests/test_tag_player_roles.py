import sqlite3
import unittest
from pathlib import Path

from scripts.tag_player_roles import tag_player_roles
from ffassistant.name_matching import list_unresolved

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestTagPlayerRoles(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (?, ?, 'RB', ?)",
            [
                (1, "James Cook", "BUF"),
                (2, "Rhamondre Stevenson", "NE"),
                (3, "Ray Davis", "BUF"),
            ],
        )
        self.conn.commit()

        self.data = {
            "bellcow": ["James Cook (BUF)"],
            "committee": ["Rhamondre Stevenson (NE)"],
            "one_injury_away": ["Ray Davis (BUF)", "Some Scrub Nobody Rostered (LAR)"],
        }

    def test_tags_each_role(self):
        result = tag_player_roles(self.data, conn=self.conn)
        self.assertEqual(result["tagged"], 3)

        tags = {
            row["player_id"]: row["tag"]
            for row in self.conn.execute("SELECT player_id, tag FROM player_role_tags").fetchall()
        }
        self.assertEqual(tags[1], "bellcow")
        self.assertEqual(tags[2], "committee")
        self.assertEqual(tags[3], "one_injury_away")

    def test_unresolved_entry_queued_not_dropped(self):
        result = tag_player_roles(self.data, conn=self.conn)
        self.assertEqual(result["unresolved"], ["Some Scrub Nobody Rostered (LAR)"])

        unresolved = list_unresolved(self.conn, source="manual_role_notes")
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["raw_name"], "Some Scrub Nobody Rostered")

    def test_team_mismatch_is_reported_but_still_tagged(self):
        data = {"bellcow": ["James Cook (MIA)"], "committee": [], "one_injury_away": []}
        result = tag_player_roles(data, conn=self.conn)

        self.assertEqual(result["tagged"], 1)
        self.assertEqual(len(result["team_mismatches"]), 1)
        self.assertIn("James Cook (MIA)", result["team_mismatches"][0])

        tag = self.conn.execute("SELECT tag FROM player_role_tags WHERE player_id = 1").fetchone()["tag"]
        self.assertEqual(tag, "bellcow")

    def test_rerun_is_idempotent(self):
        tag_player_roles(self.data, conn=self.conn)
        tag_player_roles(self.data, conn=self.conn)

        total = self.conn.execute("SELECT COUNT(*) AS c FROM player_role_tags").fetchone()["c"]
        self.assertEqual(total, 3)  # upsert, not duplicate rows

    def test_reassigning_role_overwrites_previous_tag(self):
        tag_player_roles({"bellcow": ["James Cook (BUF)"], "committee": [], "one_injury_away": []}, conn=self.conn)
        tag_player_roles({"bellcow": [], "committee": ["James Cook (BUF)"], "one_injury_away": []}, conn=self.conn)

        tag = self.conn.execute("SELECT tag FROM player_role_tags WHERE player_id = 1").fetchone()["tag"]
        self.assertEqual(tag, "committee")


if __name__ == "__main__":
    unittest.main()
