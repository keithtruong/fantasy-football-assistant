import tempfile
from pathlib import Path
from unittest.mock import patch

from ffassistant import refresh
from tests.test_api import ApiTestCase


class RefreshLogIsolatedApiTestCase(ApiTestCase):
    """run_full_refresh/run_rosters_only_refresh log to ffassistant.refresh.LOG_PATH
    by default — redirect it to a throwaway file so these tests don't write
    into the real data/refresh_log.txt."""

    def setUp(self):
        super().setUp()
        self._log_tmpdir = tempfile.TemporaryDirectory()
        self.log_path_patcher = patch.object(refresh, "LOG_PATH", Path(self._log_tmpdir.name) / "refresh_log.txt")
        self.log_path_patcher.start()

    def tearDown(self):
        self.log_path_patcher.stop()
        self._log_tmpdir.cleanup()
        super().tearDown()


class TestRefreshAllApi(RefreshLogIsolatedApiTestCase):
    @patch("ffassistant.refresh.sync_player_news_from_file")
    @patch("ffassistant.refresh.sync_ros_rankings")
    @patch("ffassistant.refresh.sync_weekly_rankings")
    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_refreshes_every_active_league_and_reports_summary(
        self, mock_sync_league, mock_weekly, mock_ros, _mock_news
    ):
        resp = self.client.post("/api/refresh_all", json={"season": 2026, "week": 1})
        self.assertEqual(resp.status_code, 200)
        mock_sync_league.assert_called_once()

        data = resp.get_json()
        self.assertEqual(data["season"], 2026)
        self.assertEqual(data["week"], 1)
        self.assertFalse(data["had_failure"])
        self.assertEqual(data["rosters"]["synced"], 1)
        self.assertEqual(data["rosters"]["total"], 1)
        self.assertEqual(mock_weekly.call_count, 3)  # full_ppr/half_ppr/non_ppr
        self.assertEqual(mock_ros.call_count, 4)  # + superflex

    @patch("ffassistant.refresh.sync_player_news_from_file")
    @patch("ffassistant.refresh.sync_ros_rankings")
    @patch("ffassistant.refresh.sync_weekly_rankings")
    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("platform down"))
    def test_one_league_failing_still_returns_200_with_failure_flagged(self, _mock_sync_league, _mock_weekly, _mock_ros, _mock_news):
        resp = self.client.post("/api/refresh_all", json={"season": 2026, "week": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["had_failure"])
        self.assertEqual(data["rosters"]["failures"], [{"league": "Test League", "error": "platform down"}])

    @patch("ffassistant.refresh.sync_player_news_from_file")
    @patch("ffassistant.refresh.sync_ros_rankings")
    @patch("ffassistant.refresh.sync_weekly_rankings")
    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_defaults_season_to_current_year(self, _mock_sync_league, _mock_weekly, _mock_ros, _mock_news):
        import datetime

        # week is passed explicitly so this doesn't fall through to the live
        # NFL-week lookup (ffassistant.season.smart_current_week) during tests.
        resp = self.client.post("/api/refresh_all", json={"week": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["season"], datetime.date.today().year)


class TestRefreshRostersApi(RefreshLogIsolatedApiTestCase):
    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_refreshes_rosters_only(self, mock_sync_league):
        resp = self.client.post("/api/refresh_rosters", json={"season": 2026, "week": 1})
        self.assertEqual(resp.status_code, 200)
        mock_sync_league.assert_called_once()

        data = resp.get_json()
        self.assertEqual(data["season"], 2026)
        self.assertEqual(data["week"], 1)
        self.assertFalse(data["had_failure"])
        self.assertEqual(data["rosters"], {"synced": 1, "total": 1, "failures": []})
        self.assertNotIn("weekly", data)
        self.assertNotIn("ros", data)
        self.assertNotIn("news", data)

    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("platform down"))
    def test_one_league_failing_still_returns_200_with_failure_flagged(self, _mock_sync_league):
        resp = self.client.post("/api/refresh_rosters", json={"season": 2026, "week": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["had_failure"])
        self.assertEqual(data["rosters"]["failures"], [{"league": "Test League", "error": "platform down"}])


if __name__ == "__main__":
    import unittest

    unittest.main()
