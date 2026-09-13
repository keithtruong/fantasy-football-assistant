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
which uses the file-based path by default.

Digest generation used to always call the Anthropic API directly regardless
of which of the two paths above was used, since it needs to know which
players are actually rostered — something only this project's own DB can
answer, and Cowork's extraction task has no visibility into. It's now
file-based too, via a second scheduled Cowork task: sync_player_news_from_file()
writes the rostered/matched news (computed locally, same as always) out to
ffassistant.config.PLAYER_DIGEST_REQUEST_PATH for that task to read, and reads
back whatever it last wrote to ffassistant.config.PLAYER_DIGESTS_IMPORT_PATH —
see _digests_from_cowork_export(). sync_player_news() still calls the API
directly for both steps, since it exists specifically for an immediate manual
one-off pull where waiting on Cowork's own schedule isn't the point.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from ffassistant import claude_news
from ffassistant.claude_news import NewsItem
from ffassistant.config import PLAYER_DIGEST_REQUEST_PATH, PLAYER_DIGESTS_IMPORT_PATH, ROTOWORLD_NEWS_IMPORT_PATH
from ffassistant.connectors import nbc_news
from ffassistant.name_matching import normalize


def sync_player_news(conn: sqlite3.Connection) -> dict:
    """Full-replace sync for player_news and player_news_digest, extracting
    items AND generating digests via direct Anthropic API calls — the
    immediate, metered path kept around for a manual one-off pull (see module
    docstring for the file-based default that avoids that cost)."""
    pages = nbc_news.fetch_recent_pages()
    items = claude_news.extract_news_items(pages)
    return _sync_items(conn, items, digest_source=claude_news.generate_digests)


def sync_player_news_from_file(conn: sqlite3.Connection, file_path=None) -> dict:
    """Full-replace sync using items already extracted by a scheduled Cowork
    task rather than calling the Anthropic API here. Raises FileNotFoundError
    if nothing's been dropped yet — deliberately not a silent fall-through to
    the paid API path, so a broken/missed Cowork run surfaces as a clear
    failure in the refresh log instead of quietly costing money again. Digest
    generation is file-based too (see _digests_from_cowork_export) — this
    function never calls the Anthropic API.

    Expected file shape: {"fetched_at": "<ISO-8601>", "items": [<NewsItem fields>, ...]}
    """
    path = file_path or ROTOWORLD_NEWS_IMPORT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — the scheduled Cowork task hasn't dropped a fresh export yet"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = [NewsItem(**item) for item in payload["items"]]
    return _sync_items(conn, items, digest_source=_digests_from_cowork_export)


def _sync_items(
    conn: sqlite3.Connection,
    items: list[NewsItem],
    digest_source: Callable[[dict[int, dict]], dict[int, str]],
) -> dict:
    players = conn.execute("SELECT player_id, full_name FROM players").fetchall()
    full_name_by_id = {row["player_id"]: row["full_name"] for row in players}
    by_normalized: dict[str, list[int]] = {}
    for row in players:
        by_normalized.setdefault(normalize(row["full_name"]), []).append(row["player_id"])

    conn.execute("DELETE FROM player_news")

    # skipped_no_link is tracked separately from the general unmatched count:
    # unlike "no canonical player" (expected — most items are about players
    # nobody rosters), a missing link on every item usually means a Rotoworld-
    # extraction Cowork trigger's prompt regressed (e.g. stopped pulling the
    # data-share-url permalink) rather than anything about the news itself —
    # see refresh_news(), which surfaces this count so a broken trigger shows
    # up in the refresh log instead of just looking like "no news today".
    skipped_no_link = 0
    matched_by_player: dict[int, list] = {}
    for item in items:
        if not item.link:
            skipped_no_link += 1  # no stable identity for this item to dedupe on — skip
            continue
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
    digests = digest_source(player_items)
    for player_id, digest in digests.items():
        conn.execute("INSERT INTO player_news_digest (player_id, digest) VALUES (?, ?)", (player_id, digest))
    conn.commit()

    return {
        "total_items": len(items),
        "matched_headlines": sum(len(v) for v in matched_by_player.values()),
        "skipped_no_link": skipped_no_link,
    }


def _digests_from_cowork_export(player_items: dict[int, dict]) -> dict[int, str]:
    """Writes the current rostered/matched news out to PLAYER_DIGEST_REQUEST_PATH
    for a second scheduled Cowork task to pick up on its own schedule, and
    reads back whatever that task's last run dropped at
    PLAYER_DIGESTS_IMPORT_PATH — so digest synthesis, like extraction, runs on
    Cowork's own Claude access instead of a metered Anthropic API call here.

    This means digests are always one Cowork cycle behind (same tradeoff the
    headline export already made). A missing/not-yet-run digest export just
    means no digests this sync, not a failure — unlike the headline file,
    there's no paid fallback path here to guard against silently sliding back
    into, and blocking the whole refresh over a still-supplementary digest
    would cost more than it protects.
    """
    _write_digest_request(player_items, PLAYER_DIGEST_REQUEST_PATH)
    return _read_digest_export(player_items, PLAYER_DIGESTS_IMPORT_PATH)


def _write_digest_request(player_items: dict[int, dict], path) -> None:
    if not player_items:
        return
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "players": [
            {
                "player_id": player_id,
                "full_name": info["full_name"],
                "items": [item.model_dump() for item in info["items"]],
            }
            for player_id, info in player_items.items()
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_digest_export(player_items: dict[int, dict], path) -> dict[int, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    digests = {int(d["player_id"]): d["digest"] for d in payload.get("digests", [])}
    # Only keep digests for players this sync actually matched rostered news
    # for — drops stale entries for anyone no longer rostered or without
    # recent news, same as a fresh generation would have.
    return {player_id: text for player_id, text in digests.items() if player_id in player_items}
