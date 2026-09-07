import unittest
from unittest.mock import patch

from ffassistant.connectors import nbc_news

SAMPLE_PAGE = """
<!DOCTYPE html>
<html>
<head><title>ignored</title><script>var x = 1;</script><style>.a{color:red}</style></head>
<body>
<nav>site nav</nav>
<header>site header</header>
<main class="Page-main">
<ul class="PlayerNewsModuleList">
<li class="PlayerNewsModuleList-item">
<div class="PlayerNewsPost">
<picture><source srcset="x.webp"/><img src="x.jpg"/></picture>
<svg><path d="M0 0"/></svg>
<h2><span class="PlayerNewsPost-firstName">Puka</span> <span class="PlayerNewsPost-lastName">Nacua</span></h2>
<span class="PlayerNewsPost-team-abbr">LA</span>
<span class="PlayerNewsPost-position">Wide Receiver</span>
<h3 class="PlayerNewsPost-headline">Expected to play Week 1</h3>
<div class="PlayerNewsPost-analysis">McVay said Nacua is trending toward playing.</div>
<!-- an html comment that should be stripped -->
<div class="PlayerNewsPost-date" data-date="2026-09-06T22:09:55.279Z"></div>
</div>
</li>
</ul>
</main>
<footer>site footer</footer>
</body>
</html>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class TestFetchRecentPages(unittest.TestCase):
    @patch("ffassistant.connectors.nbc_news.requests.get")
    def test_fetches_requested_page_count(self, mock_get):
        mock_get.return_value = FakeResponse(SAMPLE_PAGE)
        pages = nbc_news.fetch_recent_pages(max_pages=3)
        self.assertEqual(len(pages), 3)
        self.assertEqual(mock_get.call_count, 3)
        called_pages = [call.kwargs["params"]["p"] for call in mock_get.call_args_list]
        self.assertEqual(called_pages, [1, 2, 3])

    @patch("ffassistant.connectors.nbc_news.requests.get")
    def test_uses_the_player_news_url(self, mock_get):
        mock_get.return_value = FakeResponse(SAMPLE_PAGE)
        nbc_news.fetch_recent_pages(max_pages=1)
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], nbc_news.BASE_URL)


class TestClean(unittest.TestCase):
    def test_strips_noise_and_keeps_content(self):
        cleaned = nbc_news._clean(SAMPLE_PAGE)
        self.assertNotIn("var x = 1", cleaned)
        self.assertNotIn("color:red", cleaned)
        self.assertNotIn("site nav", cleaned)
        self.assertNotIn("site header", cleaned)
        self.assertNotIn("site footer", cleaned)
        self.assertNotIn("<svg>", cleaned)
        self.assertNotIn("<img", cleaned)
        self.assertNotIn("<!-- an html comment", cleaned)
        self.assertIn("Puka", cleaned)
        self.assertIn("Nacua", cleaned)
        self.assertIn("Expected to play Week 1", cleaned)
        self.assertIn("data-date=\"2026-09-06T22:09:55.279Z\"", cleaned)

    def test_narrows_to_main_when_present(self):
        cleaned = nbc_news._clean(SAMPLE_PAGE)
        # Confirms it picked <main> specifically, not the whole <body> — the
        # <footer>/<nav> text (outside <main> here) shouldn't survive even if
        # the generic tag-strip somehow missed one.
        self.assertTrue(cleaned.strip().startswith("<main"))

    def test_handles_missing_main_gracefully(self):
        html = "<html><body><div>Just a div, no main tag</div></body></html>"
        cleaned = nbc_news._clean(html)
        self.assertIn("Just a div", cleaned)

    def test_handles_malformed_html_without_raising(self):
        html = "<div><p>Unclosed paragraph<div>Nested oddly</div>"
        nbc_news._clean(html)  # must not raise


if __name__ == "__main__":
    unittest.main()
