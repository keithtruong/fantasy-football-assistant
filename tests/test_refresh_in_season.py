import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import refresh_in_season

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestRefreshInSeason(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (1, 'Active Sleeper League', 'sleeper', '999', 1, 1)"
        )
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (2, 'Inactive League', 'sleeper', '111', 1, 0)"
        )
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (3, 'Manual League', 'manual', NULL, 1, 1)"
        )
        self.conn.commit()

        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path_patcher = patch.object(refresh_in_season, "LOG_PATH", Path(self.tmpdir.name) / "refresh_log.txt")
        self.log_path_patcher.start()

        self.conn_patcher = patch.object(refresh_in_season, "get_connection", return_value=self.conn)
        self.conn_patcher.start()

    def tearDown(self):
        self.conn_patcher.stop()
        self.log_path_patcher.stop()
        self.tmpdir.cleanup()

    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_only_syncs_active_non_manual_leagues(self, mock_sync):
        results = refresh_in_season.refresh_rosters(self.conn, 2026, 1)
        self.assertEqual(len(results), 1)  # inactive and manual leagues excluded
        self.assertEqual(results[0][0], "Active Sleeper League")
        mock_sync.assert_called_once()

    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("boom"))
    def test_one_league_failing_does_not_raise(self, _mock):
        results = refresh_in_season.refresh_rosters(self.conn, 2026, 1)
        self.assertEqual(results, [("Active Sleeper League", False, "boom")])

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh_in_season, "sync_player_news")
    @patch.object(refresh_in_season, "sync_weekly_rankings")
    @patch.object(refresh_in_season, "sync_ros_rankings")
    @patch.object(refresh_in_season, "smart_current_week", return_value=3)
    def test_main_defaults_week_from_current_week_and_exits_zero_on_success(
        self, mock_current_week, mock_ros, mock_weekly, _mock_news, _mock_sleeper
    ):
        exit_code = refresh_in_season.main(["--season", "2026"])
        self.assertEqual(exit_code, 0)
        mock_current_week.assert_called_once()
        self.assertEqual(mock_weekly.call_count, len(refresh_in_season.WEEKLY_SCORING_FORMATS))
        for scoring_format in refresh_in_season.WEEKLY_SCORING_FORMATS:
            mock_weekly.assert_any_call(self.conn, 2026, 3, scoring_format)
        self.assertEqual(mock_ros.call_count, len(refresh_in_season.SCORING_FORMATS))

    @patch("ffassistant.season._fetch_live_week", return_value=None)
    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh_in_season, "sync_player_news")
    @patch.object(refresh_in_season, "sync_ros_rankings")
    def test_main_skips_weekly_when_no_current_week(self, mock_ros, _mock_news, _mock_sleeper, _mock_live):
        # No season_settings row configured and live lookup disabled -> smart_current_week() returns None.
        exit_code = refresh_in_season.main(["--season", "2026"])
        self.assertEqual(exit_code, 0)
        log_text = refresh_in_season.LOG_PATH.read_text()
        self.assertIn("Weekly rankings: SKIPPED", log_text)

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh_in_season, "sync_player_news")
    @patch.object(refresh_in_season, "sync_weekly_rankings")
    @patch.object(refresh_in_season, "sync_ros_rankings", side_effect=RuntimeError("cookie expired"))
    def test_main_exits_nonzero_when_anything_fails(self, _mock_ros, _mock_weekly, _mock_news, _mock_sleeper):
        exit_code = refresh_in_season.main(["--season", "2026", "--week", "1"])
        self.assertEqual(exit_code, 1)

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh_in_season, "sync_player_news")
    @patch.object(refresh_in_season, "sync_weekly_rankings")
    @patch.object(refresh_in_season, "sync_ros_rankings")
    def test_main_writes_to_log_file(self, _mock_ros, _mock_weekly, _mock_news, _mock_sleeper):
        refresh_in_season.main(["--season", "2026", "--week", "1"])
        self.assertTrue(refresh_in_season.LOG_PATH.exists())
        log_text = refresh_in_season.LOG_PATH.read_text()
        self.assertIn("season=2026 week=1", log_text)
        self.assertIn("Rosters/status: 1/1 leagues synced", log_text)

    @patch.object(refresh_in_season, "sync_player_news")
    def test_refresh_news_reports_count(self, mock_sync):
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Someone', 'WR')"
        )
        self.conn.execute(
            "INSERT INTO player_news (player_id, headline, link) VALUES (1, 'headline', 'https://example.com/1')"
        )
        self.conn.commit()

        ok, detail, error = refresh_in_season.refresh_news(self.conn)
        self.assertTrue(ok)
        self.assertEqual(detail, "1 headlines matched")
        self.assertIsNone(error)
        mock_sync.assert_called_once_with(self.conn)

    @patch.object(refresh_in_season, "sync_player_news", side_effect=RuntimeError("feed down"))
    def test_refresh_news_reports_failure(self, _mock_sync):
        ok, detail, error = refresh_in_season.refresh_news(self.conn)
        self.assertFalse(ok)
        self.assertIsNone(detail)
        self.assertEqual(error, "feed down")


if __name__ == "__main__":
    unittest.main()
