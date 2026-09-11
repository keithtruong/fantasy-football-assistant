"""Sync player news into the database: fetches NBC Sports' "Rotoworld"
player-news archive, then uses Claude to extract structured items and
synthesize a per-player digest (see ffassistant.claude_news). Matching a raw
name to a canonical player stays entirely deterministic
(ffassistant.name_matching) — Claude never touches identity resolution, only
interpretation of the external content. See CLAUDE.md's player-name-matching
rule for why that boundary matters.

Matching here is a lightweight, read-only lookup — deliberately NOT routed
through name_matching.match_player's alias-recording/unresolved_aliases
machinery, since most items are about players never rostered in any of
Keith's leagues at all, and queuing every miss for manual review would just
be noise. Ambiguous normalized-name collisions are skipped, not guessed at.

Two ways to get the extracted items in: sync_player_news() calls the
Anthropic API directly (extract_news_items) — a metered cost on top of
whatever Claude plan is already paying for Claude Code/Cowork. The
extraction step has no dependency on this project's own data (it's a pure
read of the public Rotoworld page), so sync_player_news_from_file() instead
reads that same shape from a JSON file a scheduled Cowork task drops at
ffassistant.config.ROTOWORLD_NEWS_IMPORT_PATH — see scripts/refresh_in_season.py,
which uses the file-based path by default. Digest generation always stays
local either way: it needs to know which players are actually rostered,
which only this project's own DB can answer.
"""

import json
import sqlite3

from ffassistant import claude_news
from ffassistant.claude_news import NewsItem
from ffassistant.config import ROTOWORLD_NEWS_IMPORT_PATH
from ffassistant.connectors import nbc_news
from ffassistant.name_matching import normalize


def sync_player_news(conn: sqlite3.Connection) -> None:
    """Full-replace sync for player_news and player_news_digest, extracting
    items via a direct Anthropic API call (see module docstring for the
    file-based alternative that avoids that cost)."""
    pages = nbc_news.fetch_recent_pages()
    items = claude_news.extract_news_items(pages)
    _sync_items(conn, items)


def sync_player_news_from_file(conn: sqlite3.Connection, file_path=None) -> None:
    """Full-replace sync using items already extracted by a scheduled Cowork
    task rather than calling the Anthropic API here. Raises FileNotFoundError
    if nothing's been dropped yet — deliberately not a silent fall-through to
    the paid API path, so a broken/missed Cowork run surfaces as a clear
    failure in the refresh log instead of quietly costing money again.

    Expected file shape: {"fetched_at": "<ISO-8601>", "items": [<NewsItem fields>, ...]}
    """
    path = file_path or ROTOWORLD_NEWS_IMPORT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — the scheduled Cowork task hasn't dropped a fresh export yet"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = [NewsItem(**item) for item in payload["items"]]
    _sync_items(conn, items)


def _sync_items(conn: sqlite3.Connection, items: list[NewsItem]) -> None:
    players = conn.execute("SELECT player_id, full_name FROM players").fetchall()
    full_name_by_id = {row["player_id"]: row["full_name"] for row in players}
    by_normalized: dict[str, list[int]] = {}
    for row in players:
        by_normalized.setdefault(normalize(row["full_name"]), []).append(row["player_id"])

    conn.execute("DELETE FROM player_news")

    matched_by_player: dict[int, list] = {}
    for item in items:
        if not item.link:
            continue  # no stable identity for this item to dedupe on — skip
        candidates = by_normalized.get(normalize(item.raw_name))
        if not candidates or len(candidates) > 1:
            continue  # no canonical match, or an ambiguous same-name collision — skip, don't guess
        player_id = candidates[0]
        conn.execute(
            "INSERT OR IGNORE INTO player_news "
            "(player_id, headline, analysis, category, source, link, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (player_id, item.headline, item.analysis, item.category, item.source, item.link, item.published_at),
        )
        matched_by_player.setdefault(player_id, []).append(item)
    conn.commit()

    # Digest only players actually on one of Keith's rosters — no point
    # summarizing news for a matched name nobody currently has.
    rostered_ids = {row["player_id"] for row in conn.execute("SELECT DISTINCT player_id FROM roster_spots")}
    player_items = {
        player_id: {"full_name": full_name_by_id[player_id], "items": matched_items}
        for player_id, matched_items in matched_by_player.items()
        if player_id in rostered_ids
    }

    conn.execute("DELETE FROM player_news_digest")
    digests = claude_news.generate_digests(player_items)
    for player_id, digest in digests.items():
        conn.execute("INSERT INTO player_news_digest (player_id, digest) VALUES (?, ?)", (player_id, digest))
    conn.commit()
