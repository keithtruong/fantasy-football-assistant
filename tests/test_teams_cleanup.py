import sqlite3
import unittest
from pathlib import Path

from ffassistant.ingest._teams import refresh_nfl_team, remove_stale_teams

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestRemoveStaleTeams(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'espn', 2)"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (1, 1, 'old1', 'Old Team')"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (2, 1, 'cur1', 'Current Team')"
        )
        self.conn.commit()

    def test_removes_team_not_in_current_sync(self):
        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=["cur1"])
        remaining = {r["platform_team_id"] for r in self.conn.execute("SELECT * FROM teams WHERE league_id = 1")}
        self.assertEqual(remaining, {"cur1"})

    def test_keeps_stale_team_with_draft_picks(self):
        self.conn.execute(
            "INSERT INTO draft_picks (league_id, season, round, pick_number, team_id, player_id) "
            "VALUES (1, 2025, 1, 1, 1, NULL)"
        )
        self.conn.commit()

        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=["cur1"])

        remaining = {r["platform_team_id"] for r in self.conn.execute("SELECT * FROM teams WHERE league_id = 1")}
        self.assertEqual(remaining, {"old1", "cur1"})  # old1 kept — real draft data depends on it

    def test_no_current_teams_removes_everything_without_picks(self):
        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=[])
        remaining = self.conn.execute("SELECT * FROM teams WHERE league_id = 1").fetchall()
        self.assertEqual(remaining, [])


class TestRefreshNflTeam(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (1, 'A', 'RB', 'DEN')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (2, 'B', 'WR', NULL)"
        )
        self.conn.commit()

    def _team(self, player_id):
        return self.conn.execute(
            "SELECT nfl_team FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()["nfl_team"]

    def test_updates_when_team_changed(self):
        refresh_nfl_team(self.conn, 1, "DAL")
        self.assertEqual(self._team(1), "DAL")

    def test_fills_a_null_team(self):
        refresh_nfl_team(self.conn, 2, "KC")
        self.assertEqual(self._team(2), "KC")

    def test_none_does_not_blank_a_known_team(self):
        refresh_nfl_team(self.conn, 1, None)
        self.assertEqual(self._team(1), "DEN")


if __name__ == "__main__":
    unittest.main()
