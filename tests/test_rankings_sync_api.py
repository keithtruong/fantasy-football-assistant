from unittest.mock import patch

from tests.test_api import ApiTestCase


class TestRankingsSyncApi(ApiTestCase):
    @patch("ffassistant.ingest.rankings.sync_tiers")
    @patch("ffassistant.ingest.rankings.sync_draft_rankings")
    def test_sync_calls_ingest_and_reports_counts(self, mock_sync_draft, mock_sync_tiers):
        resp = self.client.post("/api/rankings/sync", json={"season": 2026, "scoring_format": "full_ppr"})
        self.assertEqual(resp.status_code, 200)
        mock_sync_draft.assert_called_once()
        mock_sync_tiers.assert_called_once()

        data = resp.get_json()
        self.assertEqual(data["player_count"], 3)  # from ApiTestCase's base seed
        self.assertEqual(data["tier_count"], 0)
        self.assertEqual(data["unresolved_count"], 0)
        self.assertIsNotNone(data["synced_at"])  # base seed's rows already have fetched_at

    @patch("ffassistant.ingest.rankings.sync_draft_rankings", side_effect=RuntimeError("session cookie may be invalid/expired"))
    def test_sync_failure_returns_502_json(self, _mock):
        resp = self.client.post("/api/rankings/sync", json={"season": 2026, "scoring_format": "full_ppr"})
        self.assertEqual(resp.status_code, 502)
        self.assertIn("session cookie", resp.get_json()["description"])

    @patch("ffassistant.ingest.rankings.sync_tiers")
    @patch("ffassistant.ingest.rankings.sync_draft_rankings")
    def test_defaults_to_current_year_and_full_ppr(self, mock_sync_draft, _mock_sync_tiers):
        resp = self.client.post("/api/rankings/sync", json={})
        self.assertEqual(resp.status_code, 200)
        args, _kwargs = mock_sync_draft.call_args
        self.assertEqual(args[2], "full_ppr")


class TestSyncStatusApi(ApiTestCase):
    def test_returns_last_fetched_at_for_seeded_rankings(self):
        resp = self.client.get("/api/rankings/sync_status?season=2026&scoring_format=full_ppr")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.get_json()["synced_at"])

    def test_null_when_never_synced_for_that_combination(self):
        resp = self.client.get("/api/rankings/sync_status?season=2026&scoring_format=superflex")
        self.assertIsNone(resp.get_json()["synced_at"])


if __name__ == "__main__":
    import unittest

    unittest.main()
