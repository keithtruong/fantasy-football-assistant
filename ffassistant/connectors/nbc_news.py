"""Fetches NBC Sports' "Rotoworld" player-news archive
(nbcsports.com/fantasy/football/player-news) — public, no auth needed, paginated
via a plain `?p=N` query param.

This connector only fetches and generically shrinks the page for a downstream
LLM to read (see ffassistant.claude_news) — it deliberately does NOT parse out
individual news items via hardcoded CSS selectors/class names. The point of
routing extraction through Claude instead is resilience to a future markup
change on NBC's side; a connector that scraped specific class names here would
defeat that.
"""

import requests
from bs4 import BeautifulSoup, Comment

BASE_URL = "https://www.nbcsports.com/fantasy/football/player-news"

# Purely decorative/non-content elements, generic to any site (not NBC-specific
# class names) — safe to strip without touching the actual page structure a
# future extraction pass would need to read.
_NOISE_TAGS = (
    "script", "style", "svg", "picture", "img", "source", "head", "noscript",
    "nav", "footer", "header",
)


def fetch_recent_pages(max_pages: int = 3) -> list[str]:
    """Fetches the first `max_pages` pages (newest first) of the player-news
    archive, each cleaned down to just its main content. A fixed page count is
    a deliberately simple proxy for "the past few days" — precise, since the
    archive is date-ordered, doesn't require parsing dates before deciding
    whether to fetch another page.
    """
    pages = []
    for page_num in range(1, max_pages + 1):
        resp = requests.get(BASE_URL, params={"p": page_num}, timeout=30)
        resp.raise_for_status()
        pages.append(_clean(resp.text))
    return pages


def _clean(html: str) -> str:
    """Strips non-content chrome (scripts, styles, images, nav/header/footer)
    and narrows to the semantic <main> region when present — a generic,
    site-agnostic size reduction (~800KB -> well under 100KB on this page),
    not a site-specific extraction.
    """
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.body or soup

    for tag in root(_NOISE_TAGS):
        tag.decompose()
    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    return str(root)
