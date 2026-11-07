import unittest
from datetime import datetime, timedelta

from ffassistant.ops_check import CENTRAL, Problem, diff, find_problems


def at(day, hh, mm=0):
    # 2026-10-11 is a Sunday; 10-13 a Tuesday
    return datetime(2026, 10, day, hh, mm, tzinfo=CENTRAL)


def ok(when):
    return {"status": "ok", "finished_at": when.isoformat(), "last_ok_at": when.isoformat()}


def keys(problems):
    return {p.key for p in problems}


class TestNewsWatch(unittest.TestCase):
    def test_fresh_is_clear(self):
        now = at(11, 10)
        self.assertEqual(keys(find_problems({"news_watch": ok(now - timedelta(minutes=20))}, now)), set())

    def test_stale_during_the_day(self):
        now = at(11, 10)
        self.assertIn("news_watch_stale", keys(find_problems({"news_watch": ok(now - timedelta(hours=2))}, now)))

    def test_not_checked_overnight_or_before_grace(self):
        stale = {"news_watch": ok(at(11, 0) - timedelta(hours=6))}
        self.assertNotIn("news_watch_stale", keys(find_problems(stale, at(11, 7, 30))))

    def test_never_ran(self):
        self.assertIn("news_watch_stale", keys(find_problems({}, at(11, 12))))

    def test_error_reported(self):
        jobs = {"news_watch": {**ok(at(11, 11, 55)), "status": "error", "error": "boom"}}
        self.assertIn("news_watch_error", keys(find_problems(jobs, at(11, 12))))


class TestRecapPrep(unittest.TestCase):
    base = {"news_watch": ok(at(13, 9, 50))}

    def test_only_checked_tuesday_after_nine(self):
        self.assertNotIn("recap_prep_missing", keys(find_problems(self.base, at(13, 8, 50))))
        self.assertNotIn("recap_prep_missing", keys(find_problems({"news_watch": ok(at(14, 9, 50))}, at(14, 10))))
        self.assertIn("recap_prep_missing", keys(find_problems(self.base, at(13, 10))))

    def test_ran_today_is_clear_and_old_name_counts(self):
        self.assertNotIn("recap_prep_missing", keys(find_problems({**self.base, "recap_prep": ok(at(13, 8, 16))}, at(13, 10))))
        self.assertNotIn("recap_prep_missing", keys(find_problems({**self.base, "week_results_sync": ok(at(13, 8, 16))}, at(13, 10))))

    def test_error_today(self):
        jobs = {**self.base, "recap_prep": {**ok(at(13, 8, 16)), "status": "error", "error": "ESPN 401"}}
        found = find_problems(jobs, at(13, 10))
        self.assertIn("recap_prep_error", keys(found))
        self.assertIn("ESPN 401", next(p.message for p in found if p.key == "recap_prep_error"))


class TestRefreshAndDigests(unittest.TestCase):
    now = at(15, 12)
    base = {"news_watch": ok(at(15, 11, 50))}

    def test_refresh_only_checked_once_it_has_a_heartbeat(self):
        self.assertEqual(keys(find_problems(self.base, self.now)), set())
        self.assertIn("in_season_refresh_stale",
                      keys(find_problems({**self.base, "in_season_refresh": ok(self.now - timedelta(days=8))}, self.now)))

    def test_digests_lagging_the_request(self):
        found = find_problems(self.base, self.now, digest_request_mtime=self.now - timedelta(hours=1),
                              digests_mtime=self.now - timedelta(days=3))
        self.assertIn("digests_stale", keys(found))

    def test_digests_ran_but_empty(self):
        found = find_problems(self.base, self.now, digest_request_mtime=self.now - timedelta(hours=5),
                              digests_mtime=self.now - timedelta(hours=1), request_player_count=40, digest_count=0)
        self.assertIn("digests_empty", keys(found))

    def test_news_extract_stale(self):
        found = find_problems(self.base, self.now, news_extract_mtime=self.now - timedelta(days=4))
        self.assertIn("news_extract_stale", keys(found))


class TestDiff(unittest.TestCase):
    def test_alert_once_and_report_recovery(self):
        open_ = {"a": {"message": "A"}}
        new, cleared = diff(open_, [Problem("a", "A"), Problem("b", "B")])
        self.assertEqual([p.key for p in new], ["b"])
        self.assertEqual(cleared, [])
        new, cleared = diff({"a": {}, "b": {}}, [Problem("b", "B")])
        self.assertEqual((new, cleared), ([], ["a"]))


if __name__ == "__main__":
    unittest.main()
