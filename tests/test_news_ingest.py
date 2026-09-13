import json
import sqlite3
import tempfile
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
            return news_ingest.sync_player_news(self.conn)

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
        stats = self._sync([item])
        self.assertEqual(self.conn.execute("SELECT * FROM player_news").fetchall(), [])
        self.assertEqual(stats["skipped_no_link"], 1)

    def test_stats_report_totals(self):
        stats = self._sync([KITTLE_ITEM, UNMATCHED_ITEM, KITTLE_ITEM.model_copy(update={"link": None})])
        self.assertEqual(stats["total_items"], 3)
        self.assertEqual(stats["matched_headlines"], 1)
        self.assertEqual(stats["skipped_no_link"], 1)

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


class TestSyncPlayerNewsFromFile(unittest.TestCase):
    """sync_player_news_from_file() — reads items a scheduled Cowork task
    already extracted, rather than calling the Anthropic API here. Only the
    source of `items` differs from sync_player_news() for headline matching
    (exercised in TestSyncPlayerNews above); digest generation differs too,
    though — this path never calls the Anthropic API at all, see
    TestDigestsFromCoworkExport below."""

    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'George Kittle', 'TE')"
        )
        self.conn.commit()

        self.extract_patcher = patch("ffassistant.ingest.news.claude_news.extract_news_items")
        self.mock_extract = self.extract_patcher.start()
        self.digests_patcher = patch("ffassistant.ingest.news.claude_news.generate_digests")
        self.mock_digests = self.digests_patcher.start()

        self.tmpdir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.tmpdir.name) / "rotoworld_news.json"
        self.digests_import_patcher = patch(
            "ffassistant.ingest.news.PLAYER_DIGESTS_IMPORT_PATH", Path(self.tmpdir.name) / "player_digests.json"
        )
        self.digests_import_patcher.start()
        self.digest_request_patcher = patch(
            "ffassistant.ingest.news.PLAYER_DIGEST_REQUEST_PATH", Path(self.tmpdir.name) / "player_digest_request.json"
        )
        self.digest_request_patcher.start()

    def tearDown(self):
        self.extract_patcher.stop()
        self.digests_patcher.stop()
        self.digests_import_patcher.stop()
        self.digest_request_patcher.stop()
        self.tmpdir.cleanup()

    def _write(self, items):
        payload = {"fetched_at": "2026-09-11T12:00:00Z", "items": [i.model_dump() for i in items]}
        self.file_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_items_from_file_and_matches_known_player(self):
        self._write([KITTLE_ITEM])

        news_ingest.sync_player_news_from_file(self.conn, file_path=self.file_path)

        rows = self.conn.execute("SELECT * FROM player_news").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_id"], 1)
        self.assertEqual(rows[0]["headline"], KITTLE_ITEM.headline)

    def test_missing_file_raises_rather_than_falling_back_to_the_api(self):
        with self.assertRaises(FileNotFoundError):
            news_ingest.sync_player_news_from_file(self.conn, file_path=self.file_path)
        self.mock_extract.assert_not_called()

    def test_defaults_to_configured_import_path(self):
        with patch("ffassistant.ingest.news.ROTOWORLD_NEWS_IMPORT_PATH", self.file_path):
            self._write([KITTLE_ITEM])
            news_ingest.sync_player_news_from_file(self.conn)

        rows = self.conn.execute("SELECT * FROM player_news").fetchall()
        self.assertEqual(len(rows), 1)

    def test_never_calls_the_anthropic_api_for_digests(self):
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'sleeper', 1)")
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (1, 1, 'Mine', 1)")
        self.conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 1)")
        self.conn.commit()
        self._write([KITTLE_ITEM])

        news_ingest.sync_player_news_from_file(self.conn, file_path=self.file_path)

        self.mock_digests.assert_not_called()

    def test_reports_items_dropped_for_missing_link(self):
        # Simulates a Rotoworld-pull Cowork trigger whose prompt never extracts
        # a permalink — every item it produces has link=None and is silently
        # droppable; the stats returned here are how that becomes visible
        # (see refresh_news()) instead of just looking like "no news today".
        self._write([KITTLE_ITEM.model_copy(update={"link": None})])

        stats = news_ingest.sync_player_news_from_file(self.conn, file_path=self.file_path)

        self.assertEqual(stats["skipped_no_link"], 1)
        self.assertEqual(stats["matched_headlines"], 0)
        self.assertEqual(self.conn.execute("SELECT * FROM player_news").fetchall(), [])


class TestDigestsFromCoworkExport(unittest.TestCase):
    """_digests_from_cowork_export() — the file-based replacement for a direct
    generate_digests() API call, used by sync_player_news_from_file()."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.request_path = Path(self.tmpdir.name) / "player_digest_request.json"
        self.export_path = Path(self.tmpdir.name) / "player_digests.json"
        self.player_items = {1: {"full_name": "George Kittle", "items": [KITTLE_ITEM]}}

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_writes_request_file_for_cowork_to_pick_up(self):
        news_ingest._write_digest_request(self.player_items, self.request_path)

        payload = json.loads(self.request_path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["players"],
            [{"player_id": 1, "full_name": "George Kittle", "items": [KITTLE_ITEM.model_dump()]}],
        )

    def test_no_request_written_when_nothing_to_digest(self):
        news_ingest._write_digest_request({}, self.request_path)
        self.assertFalse(self.request_path.exists())

    def test_missing_export_file_returns_no_digests_without_raising(self):
        result = news_ingest._read_digest_export(self.player_items, self.export_path)
        self.assertEqual(result, {})

    def test_reads_digests_written_by_cowork(self):
        self.export_path.write_text(
            json.dumps({"digests": [{"player_id": 1, "digest": "Kittle is trending up."}]}), encoding="utf-8"
        )

        result = news_ingest._read_digest_export(self.player_items, self.export_path)

        self.assertEqual(result, {1: "Kittle is trending up."})

    def test_stale_digest_for_unmatched_player_is_dropped(self):
        self.export_path.write_text(
            json.dumps({"digests": [{"player_id": 999, "digest": "Not part of this sync."}]}), encoding="utf-8"
        )

        result = news_ingest._read_digest_export(self.player_items, self.export_path)

        self.assertEqual(result, {})

    def test_end_to_end_writes_request_and_reads_whatever_export_is_already_there(self):
        # Simulates a Cowork run that already happened before this sync started.
        self.export_path.write_text(
            json.dumps({"digests": [{"player_id": 1, "digest": "Kittle is trending up."}]}), encoding="utf-8"
        )

        with patch("ffassistant.ingest.news.PLAYER_DIGEST_REQUEST_PATH", self.request_path), patch(
            "ffassistant.ingest.news.PLAYER_DIGESTS_IMPORT_PATH", self.export_path
        ):
            result = news_ingest._digests_from_cowork_export(self.player_items)

        self.assertEqual(result, {1: "Kittle is trending up."})
        self.assertTrue(self.request_path.exists())  # written for the *next* Cowork run


if __name__ == "__main__":
    unittest.main()
