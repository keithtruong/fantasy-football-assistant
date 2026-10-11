import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant import run_log


class RunLogTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.log_path = d / "run_log.jsonl"
        self.status_path = d / "ops_status.json"
        # run_logged() uses the module-level paths, so point them at the temp dir.
        for name, path in (("RUN_LOG_PATH", self.log_path), ("STATUS_PATH", self.status_path)):
            patcher = patch.object(run_log, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()


class TestRecordRun(RunLogTestBase):
    def test_appends_history_and_updates_status_snapshot(self):
        run_log.record_run("news_watch", "ok", "2026-10-11T00:00:00+00:00", items=3, note="3 new")
        run_log.record_run("in_season_refresh", "error", "2026-10-11T00:01:00+00:00", error="boom")

        lines = self.log_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        status = run_log.read_status(self.status_path)
        self.assertEqual(status["news_watch"]["items"], 3)
        self.assertIsNotNone(status["news_watch"]["last_ok_at"])
        self.assertEqual(status["in_season_refresh"]["error"], "boom")
        self.assertIsNone(status["in_season_refresh"]["last_ok_at"])

    def test_skip_or_error_keeps_the_last_successful_run_time(self):
        ok = run_log.record_run("news_watch", "ok", "2026-10-11T00:00:00+00:00")
        run_log.record_run("news_watch", "skipped", "2026-10-11T00:05:00+00:00", note="quiet hours")

        entry = run_log.read_status(self.status_path)["news_watch"]
        self.assertEqual(entry["status"], "skipped")
        self.assertEqual(entry["last_ok_at"], ok["finished_at"])

    def test_read_status_is_empty_before_anything_runs(self):
        self.assertEqual(run_log.read_status(self.status_path), {})

    def test_trims_history_to_max_lines(self):
        orig = run_log.MAX_LOG_LINES
        run_log.MAX_LOG_LINES = 3
        try:
            for i in range(6):
                run_log.record_run("j", "ok", f"2026-10-11T00:0{i}:00+00:00", note="x" * 400)
        finally:
            run_log.MAX_LOG_LINES = orig
        lines = self.log_path.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[-1])["started_at"], "2026-10-11T00:05:00+00:00")


class TestRunLogged(RunLogTestBase):
    def test_records_ok_with_details(self):
        code = run_log.run_logged("job", lambda: (0, {"items": 5, "note": "five"}))
        self.assertEqual(code, 0)
        entry = run_log.read_status(self.status_path)["job"]
        self.assertEqual((entry["status"], entry["items"], entry["note"]), ("ok", 5, "five"))

    def test_nonzero_exit_code_is_an_error(self):
        self.assertEqual(run_log.run_logged("job", lambda: 1), 1)
        entry = run_log.read_status(self.status_path)["job"]
        self.assertEqual(entry["status"], "error")
        self.assertEqual(entry["error"], "exit code 1")

    def test_skipped_status_passes_through(self):
        run_log.run_logged("job", lambda: (0, {"status": "skipped", "note": "overnight"}))
        self.assertEqual(run_log.read_status(self.status_path)["job"]["status"], "skipped")

    def test_exception_is_recorded_then_reraised(self):
        def boom():
            raise ValueError("bad page")

        with self.assertRaises(ValueError):
            run_log.run_logged("job", boom)
        entry = run_log.read_status(self.status_path)["job"]
        self.assertEqual(entry["status"], "error")
        self.assertIn("bad page", entry["error"])


if __name__ == "__main__":
    unittest.main()
