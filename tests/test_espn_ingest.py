import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.ingest import espn as espn_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


FAKE_SETTINGS = {
    "team_count": 2,
    "scoring": {"PTD": 4, "PY": 0.04},
    "roster_slots": {"QB": 1, "RB": 2, "BENCH": 5},
}

FAKE_TEAMS = [
    {
        "platform_team_id": "1",
        "team_name": "Keith's Team",
        "waiver_priority": 2,
        "players": [
            {
                "source_player_id": "101",
                "full_name": "Justin Jefferson",
                "position": "WR",
                "nfl_team": "MIN",
                "injury_status": "ACTIVE",
            },
            {
                "source_player_id": "102",
                "full_name": "Banged Up Guy",
                "position": "RB",
                "nfl_team": "SEA",
                "injury_status": "QUESTIONABLE",
            },
        ],
    },
    {
        "platform_team_id": "2",
        "team_name": "Rival Team",
        "waiver_priority": 1,
        "players": [
            {
                "source_player_id": "201",
                "full_name": "Some Other Guy",
                "position": "RB",
                "nfl_team": "NYJ",
                "injury_status": "OUT",
            },
        ],
    },
]


class TestSyncLeague(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 2)"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (10, 'Justin Jefferson', 'WR')"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_full_sync_without_week_skips_player_status(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        scoring = {r["stat_key"]: r["points"] for r in self.conn.execute("SELECT * FROM league_scoring")}
        self.assertEqual(scoring, {"PTD": 4, "PY": 0.04})

        teams = self.conn.execute("SELECT * FROM teams ORDER BY platform_team_id").fetchall()
        self.assertEqual(len(teams), 2)

        # Pre-seeded canonical player matched, not duplicated.
        jefferson_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name = 'Justin Jefferson'"
        ).fetchone()["c"]
        self.assertEqual(jefferson_count, 1)

        # New players auto-created.
        new_player_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name IN ('Banged Up Guy', 'Some Other Guy')"
        ).fetchone()["c"]
        self.assertEqual(new_player_count, 2)

        # No week passed -> no player_status rows written.
        status_count = self.conn.execute("SELECT COUNT(*) AS c FROM player_status").fetchone()["c"]
        self.assertEqual(status_count, 0)

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_sync_with_week_records_injury_status(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)

        statuses = {
            r["status"]
            for r in self.conn.execute(
                """
                SELECT ps.status FROM player_status ps
                JOIN players p ON p.player_id = ps.player_id
                WHERE p.full_name = 'Banged Up Guy'
                """
            )
        }
        self.assertEqual(statuses, {"questionable"})

        out_status = self.conn.execute(
            """
            SELECT ps.status FROM player_status ps
            JOIN players p ON p.player_id = ps.player_id
            WHERE p.full_name = 'Some Other Guy'
            """
        ).fetchone()["status"]
        self.assertEqual(out_status, "out")

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_replaces_roster_without_duplicating_teams(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)

        team_count = self.conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
        self.assertEqual(team_count, 2)

        keiths_team = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '1'"
        ).fetchone()["team_id"]
        spot_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM roster_spots WHERE team_id = ?", (keiths_team,)
        ).fetchone()["c"]
        self.assertEqual(spot_count, 2)  # not 4

    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_with_fewer_teams_removes_the_dropped_one(self, mock_settings):
        # Real incident: an owner left / ESPN reassigned team IDs across seasons,
        # and old teams kept accumulating instead of being cleaned up.
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2025)

        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS[:1]):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        teams = self.conn.execute("SELECT platform_team_id FROM teams").fetchall()
        self.assertEqual([t["platform_team_id"] for t in teams], ["1"])  # "2" (Rival Team) is gone

    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_stale_team_with_draft_picks_is_not_removed(self, mock_settings):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2025)

        rival_team_id = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '2'"
        ).fetchone()["team_id"]
        self.conn.execute(
            "INSERT INTO draft_picks (league_id, season, round, pick_number, team_id, player_id) "
            "VALUES (1, 2025, 1, 1, ?, NULL)",
            (rival_team_id,),
        )
        self.conn.commit()

        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS[:1]):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        teams = {t["platform_team_id"] for t in self.conn.execute("SELECT platform_team_id FROM teams")}
        self.assertEqual(teams, {"1", "2"})  # "2" kept — real draft pick depends on it


if __name__ == "__main__":
    unittest.main()
