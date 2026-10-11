import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ffassistant import news_watch
from ffassistant.connectors import nbc_news
from scripts import watch_news

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"
BASE = "https://www.nbcsports.com/fantasy/football/player-news/2026-10-10/"
CT = timezone(timedelta(hours=-5))


def item_html(first, last, team, slug, body="Some analysis."):
    # Mirrors the real page's shape: name fragments lead, permalink sits on a
    # share button inside the item, and a related-news strip trails the item.
    return (
        f'<li class="whatever"><div><span>{first}</span> <span>{last}</span></div><span>{team}</span>'
        f"<span>Wide Receiver</span><p>{body}</p>"
        f'<button data-share-url="{BASE}{slug}">Share</button>'
        f"<div>More {first} {last} News <a>Pickens emerges from Lamb's shadow</a></div></li>"
    )


def page(*items):
    return f"<html><body><main><ul>{''.join(items)}</ul></main></body></html>"


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'TAMS', 'espn', 12)")
    conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (2, 'BC2', 'sleeper', 10)")
    conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (10, 1, 'Mine', 1)")
    conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (11, 1, 'Theirs', 0)")
    conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (20, 2, 'Mine too', 1)")
    for pid, name, pos in [(1, "DJ Moore", "WR"), (2, "Marvin Harrison Jr.", "WR"), (3, "Chris Brooks", "RB"),
                           (4, "Joshua Palmer", "WR")]:
        conn.execute("INSERT INTO players (player_id, full_name, position) VALUES (?, ?, ?)", (pid, name, pos))
    conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (10, 1, 'starter')")
    conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (20, 1, 'bench')")
    conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (10, 2, 'bench')")
    conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (11, 3, 'starter')")  # not mine
    return conn


class TestExtractFeedItems(unittest.TestCase):
    def test_pulls_permalink_slug_and_lead_text_per_item(self):
        items = nbc_news.extract_feed_items(page(
            item_html("DJ", "Moore", "BUF", "dj-moore-officially-questionable-for-week-5"),
            item_html("Chris", "Brooks", "GB", "packers-move-chris-brooks-to-injured-reserve"),
        ))
        self.assertEqual([i.slug for i in items],
                         ["dj-moore-officially-questionable-for-week-5", "packers-move-chris-brooks-to-injured-reserve"])
        self.assertTrue(items[0].lead_text.startswith("DJ Moore BUF"))
        self.assertTrue(items[1].link.endswith("/packers-move-chris-brooks-to-injured-reserve"))

    def test_page_without_permalinks_yields_nothing(self):
        self.assertEqual(nbc_news.extract_feed_items("<html><body><p>hi</p></body></html>"), [])


class TestTriageAndMatching(unittest.TestCase):
    def test_triage(self):
        self.assertEqual(news_watch.triage("joshua-palmer-ruled-out-for-mnf-vs-rams-in-week-5"), "urgent")
        self.assertEqual(news_watch.triage("steelers-send-michael-pittman-to-short-term-ir"), "urgent")
        self.assertEqual(news_watch.triage("schefter-cardinals-finalizing-marvin-harrison-jr-trade"), "urgent")
        self.assertEqual(news_watch.triage("williams-hamstring-q-tag-bagent-likely-starts"), "urgent")
        self.assertEqual(news_watch.triage("rap-lamar-jacksons-ankle-week-6-status-tbd"), "urgent")
        self.assertEqual(news_watch.triage("dj-moore-officially-questionable-for-week-5"), "info")
        self.assertEqual(news_watch.triage("dj-moore-practices-with-non-contact-jersey-sat"), "info")
        self.assertEqual(news_watch.triage("rookie-impresses-in-workout"), "info")  # "out" inside a word

    def test_match_lead_uses_normalized_prefix_and_only_my_rosters(self):
        index = news_watch.my_roster_index(make_conn())
        self.assertEqual(news_watch.match_lead("DJ Moore BUF Wide Receiver", index)["player_id"], 1)
        # Suffix dropped on the page ("Marvin Harrison"), present in the DB ("Jr.")
        self.assertEqual(news_watch.match_lead("Marvin Harrison ARI Wide Receiver", index)["player_id"], 2)
        self.assertIsNone(news_watch.match_lead("Chris Brooks GB Running Back", index))  # someone else's player
        self.assertIsNone(news_watch.match_lead("DJ Moorehead NYJ Wide Receiver", index))  # no partial-word match

    def test_roster_index_lists_every_league_the_player_is_on(self):
        entry = news_watch.my_roster_index(make_conn())["dj moore"]
        self.assertEqual(sorted(l["league"] for l in entry["leagues"]), ["BC2", "TAMS"])


class TestPoll(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.sent = []

    def run_poll(self, pages):
        return news_watch.poll(self.conn, fetch_html=lambda p: pages.get(p, page()), send=self.sent.append)

    def test_first_run_seeds_without_alerting(self):
        summary = self.run_poll({1: page(item_html("DJ", "Moore", "BUF", "dj-moore-ruled-out"))})
        self.assertTrue(summary["seeded"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM news_seen").fetchone()[0], 1)

    def test_only_new_urgent_items_about_my_players_alert(self):
        old = item_html("Chris", "Brooks", "GB", "packers-move-chris-brooks-to-injured-reserve")
        self.run_poll({1: page(old)})  # seed

        summary = self.run_poll({1: page(
            item_html("DJ", "Moore", "BUF", "dj-moore-ruled-out-for-week-6"),          # mine, urgent
            item_html("Marvin", "Harrison", "ARI", "marvin-harrison-practices-fully"),  # mine, info
            item_html("Joshua", "Palmer", "BUF", "joshua-palmer-placed-on-ir"),         # not rostered by me
            old,
        )})

        self.assertEqual((summary["new_items"], summary["matched"], summary["urgent"]), (3, 2, 1))
        self.assertEqual(len(self.sent), 1)
        alert = self.sent[0]
        self.assertEqual(alert["player"], "DJ Moore")
        self.assertEqual(alert["starting_in"], ["TAMS"])
        self.assertEqual(alert["headline"], "Dj moore ruled out for week 6")
        levels = dict(self.conn.execute("SELECT slug, alert_level FROM news_seen").fetchall())
        self.assertEqual(levels["marvin-harrison-practices-fully"], "info")
        self.assertIsNone(levels["joshua-palmer-placed-on-ir"])

    def test_failed_sends_are_counted(self):
        self.run_poll({1: page(item_html("Chris", "Brooks", "GB", "old"))})
        summary = news_watch.poll(
            self.conn,
            fetch_html=lambda p: page(item_html("DJ", "Moore", "BUF", "dj-moore-ruled-out"), item_html("Chris", "Brooks", "GB", "old")),
            send=lambda alert: {"delivered": False, "error": "503"},
        )
        self.assertEqual((summary["urgent"], summary["send_errors"]), (1, 1))

    def test_nothing_new_is_one_fetch_and_no_alerts(self):
        p1 = page(item_html("DJ", "Moore", "BUF", "dj-moore-ruled-out"))
        self.run_poll({1: p1})
        calls = []
        news_watch.poll(self.conn, fetch_html=lambda p: calls.append(p) or p1, send=self.sent.append)
        self.assertEqual(calls, [1])
        self.assertEqual(self.sent, [])

    def test_pages_further_when_every_item_on_a_page_is_new(self):
        self.run_poll({1: page(item_html("Chris", "Brooks", "GB", "old-item"))})  # seed
        summary = self.run_poll({
            1: page(item_html("Joshua", "Palmer", "BUF", "new-a")),
            2: page(item_html("DJ", "Moore", "BUF", "dj-moore-ruled-out-week-6"), item_html("Chris", "Brooks", "GB", "old-item")),
        })
        self.assertEqual((summary["pages"], summary["new_items"], summary["urgent"]), (2, 2, 1))

    def test_empty_first_page_is_an_error_not_silence(self):
        self.run_poll({1: page(item_html("DJ", "Moore", "BUF", "x"))})
        with self.assertRaises(RuntimeError):
            self.run_poll({1: "<html><body>redesigned</body></html>"})

    def test_prunes_rows_older_than_retention(self):
        self.conn.execute("INSERT INTO news_seen (link, first_seen_at) VALUES ('ancient', '2026-01-01T00:00:00+00:00')")
        self.run_poll({1: page(item_html("DJ", "Moore", "BUF", "x"))})
        self.assertIsNone(self.conn.execute("SELECT 1 FROM news_seen WHERE link = 'ancient'").fetchone())


class TestShouldPoll(unittest.TestCase):
    def test_overnight_never(self):
        self.assertFalse(news_watch.should_poll(datetime(2026, 10, 11, 3, 0, tzinfo=CT), None)[0])

    def test_sunday_morning_window_always(self):
        now = datetime(2026, 10, 11, 11, 0, tzinfo=CT)  # a Sunday
        self.assertTrue(news_watch.should_poll(now, now - timedelta(minutes=5))[0])

    def test_outside_windows_every_25_minutes(self):
        now = datetime(2026, 10, 13, 13, 0, tzinfo=CT)  # a Tuesday afternoon
        self.assertFalse(news_watch.should_poll(now, now - timedelta(minutes=10))[0])
        self.assertTrue(news_watch.should_poll(now, now - timedelta(minutes=25))[0])
        self.assertTrue(news_watch.should_poll(now, None)[0])


class TestWatchNewsCli(unittest.TestCase):
    @patch.object(watch_news, "get_connection")
    @patch.object(watch_news, "should_poll", return_value=(False, "overnight quiet hours"))
    def test_skips_outside_window(self, _should_poll, mock_conn):
        code, details = watch_news.main([], status={})
        self.assertEqual((code, details["status"]), (0, "skipped"))
        mock_conn.assert_not_called()

    @patch.object(watch_news, "get_connection")
    @patch.object(watch_news, "poll", return_value={"pages": 1, "new_items": 1, "matched": 1, "urgent": 1,
                                                    "send_errors": 1, "seeded": False})
    def test_failed_sends_make_the_run_an_error(self, _poll, _conn):
        code, details = watch_news.main(["--force"])
        self.assertEqual(code, 1)
        self.assertIn("failed to send", details["error"])

    @patch.object(watch_news, "get_connection")
    @patch.object(watch_news, "poll", return_value={"pages": 1, "new_items": 2, "matched": 1, "urgent": 1, "seeded": False})
    def test_force_polls_and_reports_counts(self, _poll, _conn):
        code, details = watch_news.main(["--force"])
        self.assertEqual((code, details["items"]), (0, 2))
        self.assertIn("1 urgent", details["note"])


if __name__ == "__main__":
    unittest.main()
