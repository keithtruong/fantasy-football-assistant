from unittest.mock import patch

from tests.test_api import ApiTestCase


class TestNewsSyncApi(ApiTestCase):
    @patch("ffassistant.ingest.news.sync_player_news_from_file")
    def test_sync_calls_ingest_and_reports_counts(self, mock_sync):
        resp = self.client.post("/api/news/sync")
        self.assertEqual(resp.status_code, 200)
        mock_sync.assert_called_once()
        data = resp.get_json()
        self.assertIn("player_count", data)
        self.assertIn("headline_count", data)
        self.assertIn("synced_at", data)

    @patch("ffassistant.ingest.news.sync_player_news_from_file", side_effect=RuntimeError("feed unreachable"))
    def test_sync_failure_returns_502_json(self, _mock):
        resp = self.client.post("/api/news/sync")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("feed unreachable", resp.get_json()["description"])


class TestNewsSyncStatusApi(ApiTestCase):
    def test_null_when_never_synced(self):
        resp = self.client.get("/api/news/sync_status")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json()["synced_at"])
        self.assertEqual(resp.get_json()["headline_count"], 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
