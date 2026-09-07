import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.claude_news import NewsItem
from ffassistant.ingest import news as news_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


KITTLE_ITEM = NewsItem(
    raw_name="George Kittle",
    team="SF",
    position="TE",
    headline="In line to practice Monday",
    analysis="Kittle (Achilles) is slated to practice Monday.",
    category="Injury",
    published_at="2026-09-06T22:05:00+00:00",
    source="Matt Barrows",
    link="https://www.nbcsports.com/fantasy/football/player-news/2026-09-06/kittle-line-practice-monday",
)

UNMATCHED_ITEM = NewsItem(
    raw_name="Some Random Guy Never In Our System",
    headline="Signs with practice squad",
    link="https://www.nbcsports.com/fantasy/football/player-news/2026-09-06/some-guy-signs",
)


class TestSyncPlayerNews(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'George Kittle', 'TE')"
        )
        self.conn.commit()

        self.pages_patcher = patch("ffassistant.ingest.news.nbc_news.fetch_recent_pages", return_value=["<html></html>"])
        self.pages_patcher.start()
        self.digests_patcher = patch("ffassistant.ingest.news.claude_news.generate_digests", return_value={})
        self.mock_digests = self.digests_patcher.start()

    def tearDown(self):
        self.pages_patcher.stop()
        self.digests_patcher.stop()

    def _sync(self, items):
        with patch("ffassistant.ingest.news.claude_news.extract_news_items", return_value=items):
            news_ingest.sync_player_news(self.conn)

    def test_matches_known_player_and_writes_all_fields(self):
        self._sync([KITTLE_ITEM, UNMATCHED_ITEM])

        rows = self.conn.execute("SELECT * FROM player_news").fetchall()
        self.assertEqual(len(rows), 1)  # unmatched item skipped
        row = rows[0]
        self.assertEqual(row["player_id"], 1)
        self.assertEqual(row["headline"], KITTLE_ITEM.headline)
        self.assertEqual(row["analysis"], KITTLE_ITEM.analysis)
        self.assertEqual(row["category"], KITTLE_ITEM.category)
        self.assertEqual(row["source"], KITTLE_ITEM.source)
        self.assertEqual(row["published_at"], KITTLE_ITEM.published_at)

        # No alias/unresolved-review side effects — this is a best-effort, read-only lookup.
        self.assertEqual(self.conn.execute("SELECT * FROM unresolved_aliases").fetchall(), [])
        self.assertEqual(self.conn.execute("SELECT * FROM player_aliases").fetchall(), [])

    def test_ambiguous_name_is_skipped(self):
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (2, 'George Kittle', 'QB')"
        )
        self.conn.commit()

        self._sync([KITTLE_ITEM])

        self.assertEqual(self.conn.execute("SELECT * FROM player_news").fetchall(), [])

    def test_item_without_link_is_skipped(self):
        item = KITTLE_ITEM.model_copy(update={"link": None})
        self._sync([item])
        self.assertEqual(self.conn.execute("SELECT * FROM player_news").fetchall(), [])

    def test_resync_fully_replaces_stale_rows(self):
        self._sync([KITTLE_ITEM])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"], 1)

        self._sync([])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"], 0)

    def test_digest_only_requested_for_rostered_players(self):
        # George Kittle matched but not rostered anywhere -> excluded from the digest call.
        self._sync([KITTLE_ITEM])
        self.mock_digests.assert_called_once_with({})

    def test_digest_requested_for_rostered_player_with_full_name_and_items(self):
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'sleeper', 1)")
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (1, 1, 'Mine', 1)")
        self.conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 1)")
        self.conn.commit()

        self._sync([KITTLE_ITEM])

        args, _kwargs = self.mock_digests.call_args
        player_items = args[0]
        self.assertEqual(set(player_items.keys()), {1})
        self.assertEqual(player_items[1]["full_name"], "George Kittle")
        self.assertEqual(player_items[1]["items"], [KITTLE_ITEM])

    def test_digest_rows_written_and_fully_replaced(self):
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'sleeper', 1)")
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (1, 1, 'Mine', 1)")
        self.conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 1)")
        self.conn.commit()
        self.mock_digests.return_value = {1: "Kittle is dealing with an Achilles issue but expected to play."}

        self._sync([KITTLE_ITEM])

        row = self.conn.execute("SELECT * FROM player_news_digest WHERE player_id = 1").fetchone()
        self.assertEqual(row["digest"], "Kittle is dealing with an Achilles issue but expected to play.")

        self.mock_digests.return_value = {}
        self._sync([KITTLE_ITEM])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS c FROM player_news_digest").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
