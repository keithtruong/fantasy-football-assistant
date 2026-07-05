import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.ingest import yahoo as yahoo_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


FAKE_SETTINGS = {
    "team_count": 2,
    "scoring": {"pass_td": 4.0, "int": -1.0},
    "roster_slots": {"QB": 1, "RB": 2, "BENCH": 5},
}

FAKE_TEAMS = [
    {
        "platform_team_id": "5",
        "team_name": "Long Balls",
        "waiver_priority": 9,
        "players": [
            {
                "source_player_id": "34218",
                "full_name": "Brock Purdy",
                "position": "QB",
                "nfl_team": "SF",
                "injury_status": "healthy",
            },
            {
                "source_player_id": "33965",
                "full_name": "Banged Up Guy",
                "position": "WR",
                "nfl_team": "NYJ",
                "injury_status": "questionable",
            },
        ],
    },
    {
        "platform_team_id": "6",
        "team_name": "Rival Team",
        "waiver_priority": 1,
        "players": [
            {
                "source_player_id": "201",
                "full_name": "Some Other Guy",
                "position": "RB",
                "nfl_team": "NYJ",
                "injury_status": "out",
            },
        ],
    },
]


class TestSyncLeague(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'yahoo', 2)"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (10, 'Brock Purdy', 'QB')"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.yahoo.yahoo_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.yahoo.yahoo_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_full_sync_without_week_skips_player_status(self, *_mocks):
        yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2025)

        scoring = {r["stat_key"]: r["points"] for r in self.conn.execute("SELECT * FROM league_scoring")}
        self.assertEqual(scoring, {"pass_td": 4.0, "int": -1.0})

        teams = self.conn.execute("SELECT * FROM teams ORDER BY platform_team_id").fetchall()
        self.assertEqual(len(teams), 2)

        purdy_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name = 'Brock Purdy'"
        ).fetchone()["c"]
        self.assertEqual(purdy_count, 1)  # matched, not duplicated

        new_player_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name IN ('Banged Up Guy', 'Some Other Guy')"
        ).fetchone()["c"]
        self.assertEqual(new_player_count, 2)

        status_count = self.conn.execute("SELECT COUNT(*) AS c FROM player_status").fetchone()["c"]
        self.assertEqual(status_count, 0)

    @patch("ffassistant.ingest.yahoo.yahoo_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.yahoo.yahoo_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_sync_with_week_records_injury_status(self, *_mocks):
        yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2025, week=10)

        status = self.conn.execute(
            """
            SELECT ps.status FROM player_status ps
            JOIN players p ON p.player_id = ps.player_id
            WHERE p.full_name = 'Banged Up Guy'
            """
        ).fetchone()["status"]
        self.assertEqual(status, "questionable")

    @patch("ffassistant.ingest.yahoo.yahoo_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.yahoo.yahoo_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_replaces_roster_without_duplicating_teams(self, *_mocks):
        yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2025, week=10)
        yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2025, week=10)

        team_count = self.conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
        self.assertEqual(team_count, 2)

        long_balls = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '5'"
        ).fetchone()["team_id"]
        spot_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM roster_spots WHERE team_id = ?", (long_balls,)
        ).fetchone()["c"]
        self.assertEqual(spot_count, 2)  # not 4

    @patch("ffassistant.ingest.yahoo.yahoo_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_with_fewer_teams_removes_the_dropped_one(self, _mock_settings):
        with patch("ffassistant.ingest.yahoo.yahoo_api.get_teams", return_value=FAKE_TEAMS):
            yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2025)

        with patch("ffassistant.ingest.yahoo.yahoo_api.get_teams", return_value=FAKE_TEAMS[:1]):
            yahoo_ingest.sync_league(self.conn, league_id=1, yahoo_league_id="461.l.656302", season=2026)

        teams = self.conn.execute("SELECT platform_team_id FROM teams").fetchall()
        self.assertEqual([t["platform_team_id"] for t in teams], ["5"])


if __name__ == "__main__":
    unittest.main()
