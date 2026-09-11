import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant import refresh

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestRefresh(unittest.TestCase):
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
        self.log_path_patcher = patch.object(refresh, "LOG_PATH", Path(self.tmpdir.name) / "refresh_log.txt")
        self.log_path_patcher.start()

    def tearDown(self):
        self.log_path_patcher.stop()
        self.tmpdir.cleanup()

    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_only_syncs_active_non_manual_leagues(self, mock_sync):
        results = refresh.refresh_rosters(self.conn, 2026, 1)
        self.assertEqual(len(results), 1)  # inactive and manual leagues excluded
        self.assertEqual(results[0][0], "Active Sleeper League")
        mock_sync.assert_called_once()

    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("boom"))
    def test_one_league_failing_does_not_raise(self, _mock):
        results = refresh.refresh_rosters(self.conn, 2026, 1)
        self.assertEqual(results, [("Active Sleeper League", False, "boom")])

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh, "sync_player_news_from_file")
    @patch.object(refresh, "sync_weekly_rankings")
    @patch.object(refresh, "sync_ros_rankings")
    @patch.object(refresh, "smart_current_week", return_value=3)
    def test_run_full_refresh_defaults_week_from_current_week_and_reports_success(
        self, mock_current_week, mock_ros, mock_weekly, _mock_news, _mock_sleeper
    ):
        summary = refresh.run_full_refresh(self.conn, season=2026)
        self.assertFalse(summary["had_failure"])
        mock_current_week.assert_called_once()
        self.assertEqual(mock_weekly.call_count, len(refresh.WEEKLY_SCORING_FORMATS))
        for scoring_format in refresh.WEEKLY_SCORING_FORMATS:
            mock_weekly.assert_any_call(self.conn, 2026, 3, scoring_format)
        self.assertEqual(mock_ros.call_count, len(refresh.SCORING_FORMATS))

    @patch("ffassistant.season._fetch_live_week", return_value=None)
    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh, "sync_player_news_from_file")
    @patch.object(refresh, "sync_ros_rankings")
    def test_run_full_refresh_skips_weekly_when_no_current_week(self, mock_ros, _mock_news, _mock_sleeper, _mock_live):
        # No season_settings row configured and live lookup disabled -> smart_current_week() returns None.
        summary = refresh.run_full_refresh(self.conn, season=2026)
        self.assertFalse(summary["had_failure"])
        self.assertTrue(summary["weekly"]["skipped"])
        log_text = refresh.LOG_PATH.read_text()
        self.assertIn("Weekly rankings: SKIPPED", log_text)

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh, "sync_player_news_from_file")
    @patch.object(refresh, "sync_weekly_rankings")
    @patch.object(refresh, "sync_ros_rankings", side_effect=RuntimeError("cookie expired"))
    def test_run_full_refresh_flags_failure_when_anything_fails(self, _mock_ros, _mock_weekly, _mock_news, _mock_sleeper):
        summary = refresh.run_full_refresh(self.conn, season=2026, week=1)
        self.assertTrue(summary["had_failure"])
        self.assertEqual(len(summary["ros"]["errors"]), len(refresh.SCORING_FORMATS))
        self.assertIn("full_ppr: cookie expired", summary["ros"]["errors"])

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh, "sync_player_news_from_file")
    @patch.object(refresh, "sync_weekly_rankings")
    @patch.object(refresh, "sync_ros_rankings")
    def test_run_full_refresh_writes_to_log_file(self, _mock_ros, _mock_weekly, _mock_news, _mock_sleeper):
        refresh.run_full_refresh(self.conn, season=2026, week=1)
        self.assertTrue(refresh.LOG_PATH.exists())
        log_text = refresh.LOG_PATH.read_text()
        self.assertIn("season=2026 week=1", log_text)
        self.assertIn("Rosters/status: 1/1 leagues synced", log_text)

    @patch.object(refresh, "sync_player_news_from_file")
    def test_refresh_news_reports_count(self, mock_sync):
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Someone', 'WR')"
        )
        self.conn.execute(
            "INSERT INTO player_news (player_id, headline, link) VALUES (1, 'headline', 'https://example.com/1')"
        )
        self.conn.commit()

        ok, detail, error = refresh.refresh_news(self.conn)
        self.assertTrue(ok)
        self.assertEqual(detail, "1 headlines matched")
        self.assertIsNone(error)
        mock_sync.assert_called_once_with(self.conn)

    @patch.object(refresh, "sync_player_news_from_file", side_effect=RuntimeError("feed down"))
    def test_refresh_news_reports_failure(self, _mock_sync):
        ok, detail, error = refresh.refresh_news(self.conn)
        self.assertFalse(ok)
        self.assertIsNone(detail)
        self.assertEqual(error, "feed down")


class TestRunRostersOnlyRefresh(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (1, 'Active Sleeper League', 'sleeper', '999', 1, 1)"
        )
        self.conn.commit()

        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path_patcher = patch.object(refresh, "LOG_PATH", Path(self.tmpdir.name) / "refresh_log.txt")
        self.log_path_patcher.start()

    def tearDown(self):
        self.log_path_patcher.stop()
        self.tmpdir.cleanup()

    @patch("ffassistant.ingest.sleeper.sync_league")
    @patch.object(refresh, "sync_player_news_from_file")
    @patch.object(refresh, "sync_weekly_rankings")
    @patch.object(refresh, "sync_ros_rankings")
    def test_only_touches_rosters(self, mock_ros, mock_weekly, mock_news, mock_sleeper):
        summary = refresh.run_rosters_only_refresh(self.conn, season=2026, week=1)
        self.assertFalse(summary["had_failure"])
        self.assertEqual(summary["rosters"], {"synced": 1, "total": 1, "failures": []})
        self.assertNotIn("weekly", summary)
        self.assertNotIn("ros", summary)
        self.assertNotIn("news", summary)
        mock_sleeper.assert_called_once()
        mock_ros.assert_not_called()
        mock_weekly.assert_not_called()
        mock_news.assert_not_called()

    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("boom"))
    def test_flags_failure_and_logs_it(self, _mock_sleeper):
        summary = refresh.run_rosters_only_refresh(self.conn, season=2026, week=1)
        self.assertTrue(summary["had_failure"])
        self.assertEqual(summary["rosters"]["failures"], [{"league": "Active Sleeper League", "error": "boom"}])
        # _write_log always writes utf-8 explicitly — read it back the same way
        # rather than the platform default (cp1252 on Windows), which would
        # mis-decode the em dash and fail this assertion.
        log_text = refresh.LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("(rosters only)", log_text)
        self.assertIn("FAILED — Active Sleeper League: boom", log_text)


if __name__ == "__main__":
    unittest.main()
