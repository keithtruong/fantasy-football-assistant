import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.ingest import sleeper as sleeper_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


FAKE_SETTINGS = {
    "team_count": 2,
    "scoring": {"rec": 1, "pass_td": 4},
    "roster_slots": {"QB": 1, "RB": 2, "BENCH": 3},
}

FAKE_TEAMS = [
    {"platform_team_id": "1", "team_name": "Keith's Team", "waiver_priority": 2, "player_ids": ["p1", "p2"]},
    {"platform_team_id": "2", "team_name": "Rival Team", "waiver_priority": 1, "player_ids": ["p3"]},
]

FAKE_ROSTER_PLAYERS = {
    "p1": {
        "source_player_id": "p1",
        "full_name": "Justin Jefferson",
        "position": "WR",
        "nfl_team": "MIN",
        "injury_status": None,
    },
    "p2": {
        "source_player_id": "p2",
        "full_name": "Kenneth Walker",
        "position": "RB",
        "nfl_team": "SEA",
        "injury_status": "Questionable",
    },
    "p3": {
        "source_player_id": "p3",
        "full_name": "Brand New Rookie",
        "position": "RB",
        "nfl_team": "NYJ",
        "injury_status": "Out",
    },
}


def fake_get_roster_players(player_ids, players_lookup):
    return [FAKE_ROSTER_PLAYERS[pid] for pid in player_ids]


class TestSyncLeague(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'sleeper', 2)"
        )
        # Pre-seed one canonical player so we can verify existing-player matching.
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (10, 'Justin Jefferson', 'WR')"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.sleeper.sleeper_api.get_roster_players", side_effect=fake_get_roster_players)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_players_lookup", return_value={})
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_full_sync_populates_settings_teams_and_rosters(self, *_mocks):
        sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")

        scoring = {r["stat_key"]: r["points"] for r in self.conn.execute("SELECT * FROM league_scoring")}
        self.assertEqual(scoring, {"rec": 1, "pass_td": 4})

        slots = {r["slot_name"]: r["slot_count"] for r in self.conn.execute("SELECT * FROM roster_slots")}
        self.assertEqual(slots, {"QB": 1, "RB": 2, "BENCH": 3})

        teams = self.conn.execute("SELECT * FROM teams ORDER BY platform_team_id").fetchall()
        self.assertEqual(len(teams), 2)
        self.assertEqual(teams[0]["team_name"], "Keith's Team")

        # Existing canonical player should be matched, not duplicated.
        jefferson_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name = 'Justin Jefferson'"
        ).fetchone()["c"]
        self.assertEqual(jefferson_count, 1)

        # A brand-new player (no canonical row, no alias) gets auto-created.
        rookie = self.conn.execute(
            "SELECT * FROM players WHERE full_name = 'Brand New Rookie'"
        ).fetchone()
        self.assertIsNotNone(rookie)

        # And the unresolved-names queue should be clean (auto-create clears it).
        unresolved = self.conn.execute("SELECT * FROM unresolved_aliases").fetchall()
        self.assertEqual(len(unresolved), 0)

        # Roster spot counts match each team's player list.
        keiths_team = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '1'"
        ).fetchone()["team_id"]
        spot_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM roster_spots WHERE team_id = ?", (keiths_team,)
        ).fetchone()["c"]
        self.assertEqual(spot_count, 2)

    @patch("ffassistant.ingest.sleeper.sleeper_api.get_roster_players", side_effect=fake_get_roster_players)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_players_lookup", return_value={})
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_replaces_roster_without_duplicating_teams(self, *_mocks):
        sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")
        sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")

        team_count = self.conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
        self.assertEqual(team_count, 2)

        keiths_team = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '1'"
        ).fetchone()["team_id"]
        spot_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM roster_spots WHERE team_id = ?", (keiths_team,)
        ).fetchone()["c"]
        self.assertEqual(spot_count, 2)  # not 4 — re-sync didn't double up

    @patch("ffassistant.ingest.sleeper.sleeper_api.get_roster_players", side_effect=fake_get_roster_players)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_players_lookup", return_value={})
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_with_fewer_teams_removes_the_dropped_one(self, *_mocks):
        with patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS):
            sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")

        with patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS[:1]):
            sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")

        teams = self.conn.execute("SELECT platform_team_id FROM teams").fetchall()
        self.assertEqual([t["platform_team_id"] for t in teams], ["1"])

    @patch("ffassistant.ingest.sleeper.sleeper_api.get_roster_players", side_effect=fake_get_roster_players)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_players_lookup", return_value={})
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_sync_with_week_records_injury_status(self, *_mocks):
        sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999", season=2026, week=5)

        statuses = {
            r["full_name"]: r["status"]
            for r in self.conn.execute(
                """
                SELECT p.full_name, ps.status FROM player_status ps
                JOIN players p ON p.player_id = ps.player_id
                """
            )
        }
        self.assertEqual(statuses["Justin Jefferson"], "healthy")  # None -> healthy fallback
        self.assertEqual(statuses["Kenneth Walker"], "questionable")
        self.assertEqual(statuses["Brand New Rookie"], "out")

    @patch("ffassistant.ingest.sleeper.sleeper_api.get_roster_players", side_effect=fake_get_roster_players)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_players_lookup", return_value={})
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.sleeper.sleeper_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_sync_without_week_skips_player_status(self, *_mocks):
        sleeper_ingest.sync_league(self.conn, league_id=1, sleeper_league_id="999")

        status_count = self.conn.execute("SELECT COUNT(*) AS c FROM player_status").fetchone()["c"]
        self.assertEqual(status_count, 0)


class TestInjuryStatusMap(unittest.TestCase):
    def test_maps_all_known_sleeper_statuses(self):
        expected = {
            "Questionable": "questionable",
            "Doubtful": "questionable",
            "Out": "out",
            "IR": "ir",
            "PUP": "ir",
            "Sus": "suspended",
            "COV": "out",
            "DNR": "out",
            "NA": "out",
        }
        for sleeper_status, mapped in expected.items():
            self.assertEqual(sleeper_ingest._INJURY_STATUS_MAP[sleeper_status], mapped)

    def test_unmapped_status_falls_back_to_healthy(self):
        self.assertEqual(sleeper_ingest._INJURY_STATUS_MAP.get("SomethingNew", "healthy"), "healthy")


if __name__ == "__main__":
    unittest.main()
