import unittest
from unittest.mock import MagicMock, patch

from ffassistant.claude_news import NewsItem, extract_news_items, generate_digests


class TestExtractNewsItems(unittest.TestCase):
    @patch("ffassistant.claude_news.anthropic.Anthropic")
    def test_returns_parsed_items(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        expected_items = [NewsItem(raw_name="Puka Nacua", headline="Expected to play", link="https://x/1")]
        mock_client.messages.parse.return_value = MagicMock(parsed_output=MagicMock(items=expected_items))

        result = extract_news_items(["<html>page content</html>"])

        self.assertEqual(result, expected_items)
        _args, kwargs = mock_client.messages.parse.call_args
        self.assertEqual(kwargs["model"], "claude-opus-5")

    @patch("ffassistant.claude_news.anthropic.Anthropic")
    def test_empty_pages_returns_empty_without_calling_api(self, mock_anthropic_cls):
        result = extract_news_items([])
        self.assertEqual(result, [])
        mock_anthropic_cls.assert_not_called()

    @patch("ffassistant.claude_news.anthropic.Anthropic")
    def test_joins_multiple_pages_with_a_separator(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.parse.return_value = MagicMock(parsed_output=MagicMock(items=[]))

        extract_news_items(["PAGE ONE CONTENT", "PAGE TWO CONTENT"])

        _args, kwargs = mock_client.messages.parse.call_args
        content = kwargs["messages"][0]["content"]
        self.assertIn("PAGE ONE CONTENT", content)
        self.assertIn("PAGE TWO CONTENT", content)
        self.assertIn("PAGE BREAK", content)


class TestGenerateDigests(unittest.TestCase):
    @patch("ffassistant.claude_news.anthropic.Anthropic")
    def test_empty_input_returns_empty_without_calling_api(self, mock_anthropic_cls):
        result = generate_digests({})
        self.assertEqual(result, {})
        mock_anthropic_cls.assert_not_called()

    @patch("ffassistant.claude_news.anthropic.Anthropic")
    def test_maps_response_by_player_id(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        digests = [MagicMock(player_id=1, digest="Doing well."), MagicMock(player_id=2, digest="Injured.")]
        mock_client.messages.parse.return_value = MagicMock(parsed_output=MagicMock(digests=digests))

        item = NewsItem(raw_name="X", headline="Some headline", link="https://x/1")
        result = generate_digests(
            {
                1: {"full_name": "Player One", "items": [item]},
                2: {"full_name": "Player Two", "items": [item]},
            }
        )

        self.assertEqual(result, {1: "Doing well.", 2: "Injured."})
        _args, kwargs = mock_client.messages.parse.call_args
        content = kwargs["messages"][0]["content"]
        self.assertIn("Player ID 1: Player One", content)
        self.assertIn("Player ID 2: Player Two", content)
        self.assertIn("Some headline", content)


if __name__ == "__main__":
    unittest.main()
