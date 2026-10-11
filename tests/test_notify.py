import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant import notify

ALERT = {
    "kind": "player_news", "level": "urgent", "player_id": 1, "player": "DJ Moore",
    "headline": "Dj moore ruled out for week 6", "link": "https://example.com/dj",
    "leagues": [{"league": "TAMS", "roster_status": "starter"}, {"league": "BC2", "roster_status": "bench"}],
    "starting_in": ["TAMS"],
}


class TestSend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "alerts.jsonl"
        patcher = patch.object(notify.config, "GROUPME_BOT_ID", "tams-bot")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def logged(self):
        return [json.loads(l) for l in self.path.read_text().splitlines()]

    @patch.object(notify.groupme, "post_message")
    def test_no_alerts_bot_configured_is_log_only_not_a_failure(self, mock_post):
        record = notify.send(ALERT, alerts_path=self.path, bot_id="")
        mock_post.assert_not_called()
        self.assertFalse(record["delivered"])
        self.assertIsNone(record["error"])
        self.assertEqual(self.logged()[0]["player"], "DJ Moore")

    @patch.object(notify.groupme, "post_message")
    def test_posts_with_the_alerts_bot_explicitly(self, mock_post):
        record = notify.send(ALERT, alerts_path=self.path, bot_id="alerts-bot")
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["bot_id"], "alerts-bot")
        self.assertTrue(record["delivered"])

    @patch.object(notify.groupme, "post_message")
    def test_refuses_to_post_alerts_to_the_tams_bot(self, mock_post):
        record = notify.send(ALERT, alerts_path=self.path, bot_id="tams-bot")
        mock_post.assert_not_called()
        self.assertFalse(record["delivered"])
        self.assertIn("TAMS", record["error"])

    @patch.object(notify.groupme, "post_message", side_effect=RuntimeError("503"))
    def test_delivery_failure_is_recorded_not_raised(self, _post):
        record = notify.send(ALERT, alerts_path=self.path, bot_id="alerts-bot")
        self.assertFalse(record["delivered"])
        self.assertIn("503", record["error"])
        self.assertEqual(len(self.logged()), 1)


class TestFormatMessage(unittest.TestCase):
    def test_player_news_lines(self):
        text = notify.format_message(ALERT)
        lines = text.splitlines()
        self.assertIn("DJ Moore: Dj moore ruled out for week 6", lines[0])
        self.assertEqual(lines[1], "Starting in: TAMS")
        self.assertEqual(lines[2], "Also on: BC2")
        self.assertEqual(lines[3], "https://example.com/dj")

    def test_capped_at_groupme_limit(self):
        self.assertEqual(len(notify.format_message({"text": "x" * 5000})), notify.GROUPME_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
