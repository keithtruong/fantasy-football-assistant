import unittest
from unittest.mock import MagicMock, patch

from ffassistant.connectors import groupme


class TestPostMessage(unittest.TestCase):
    @patch("ffassistant.connectors.groupme.requests.post")
    def test_posts_with_explicit_bot_id(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)

        groupme.post_message("Recap is live: https://example.com", bot_id="abc123")

        mock_post.assert_called_once_with(
            groupme.GROUPME_BOTS_POST_URL,
            json={"bot_id": "abc123", "text": "Recap is live: https://example.com"},
            timeout=10,
        )

    @patch("ffassistant.connectors.groupme.GROUPME_BOT_ID", "configured-bot-id")
    @patch("ffassistant.connectors.groupme.requests.post")
    def test_falls_back_to_configured_bot_id(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)

        groupme.post_message("hello")

        mock_post.assert_called_once_with(
            groupme.GROUPME_BOTS_POST_URL,
            json={"bot_id": "configured-bot-id", "text": "hello"},
            timeout=10,
        )

    @patch("ffassistant.connectors.groupme.GROUPME_BOT_ID", None)
    def test_raises_without_any_bot_id(self):
        with self.assertRaises(ValueError):
            groupme.post_message("hello")

    @patch("ffassistant.connectors.groupme.requests.post")
    def test_raises_on_error_response(self, mock_post):
        response = MagicMock(status_code=400)
        response.raise_for_status.side_effect = groupme.requests.HTTPError("bad request")
        mock_post.return_value = response

        with self.assertRaises(groupme.requests.HTTPError):
            groupme.post_message("hello", bot_id="abc123")


if __name__ == "__main__":
    unittest.main()
