import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import weekly_recap_prep as prep


class TestWeeklyRecapPrep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        drafts = Path(self.tmp.name)
        for target, value in ((prep.prepare_weekly_recap, "DRAFTS_DIR"),):
            p = patch.object(target, value, drafts)
            p.start()
            self.addCleanup(p.stop)
        self.drafts = drafts
        p = patch.object(prep, "get_connection", return_value=MagicMock())
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_prepare(self, argv):
        week = argv[argv.index("--week") + 1]
        (self.drafts / f"3_2026_wk{week}_brief.json").write_text(json.dumps([{"key": "a"}, {"key": "b"}]))
        return 0

    @patch.object(prep.sync_week_results, "_resolve_week", return_value=5)
    def test_resolves_week_once_and_passes_it_to_both_steps(self, _resolve):
        with patch.object(prep.sync_week_results, "main", return_value=0) as sync_main, \
             patch.object(prep.prepare_weekly_recap, "main", side_effect=self.fake_prepare) as prep_main:
            code, details = prep.main(["--league-id", "3", "--season", "2026"])
        self.assertEqual(code, 0)
        expected = ["--league-id", "3", "--season", "2026", "--week", "5"]
        sync_main.assert_called_once_with(expected)
        prep_main.assert_called_once_with(expected)
        self.assertEqual(details["items"], 2)
        status = json.loads((self.drafts / "3_2026_wk5_status.json").read_text())
        self.assertEqual((status["week"], status["stage"]), (5, "brief_ready"))

    @patch.object(prep.sync_week_results, "_resolve_week", return_value=5)
    def test_failed_sync_stops_before_the_brief(self, _resolve):
        with patch.object(prep.sync_week_results, "main", return_value=1), \
             patch.object(prep.prepare_weekly_recap, "main") as prep_main:
            code, details = prep.main(["--league-id", "3", "--season", "2026"])
        self.assertEqual(code, 1)
        prep_main.assert_not_called()
        self.assertIn("sync failed", details["error"])
        self.assertFalse((self.drafts / "3_2026_wk5_status.json").exists())

    def test_rerun_never_reopens_a_published_week(self):
        prep.write_stage(3, 2026, 5, "brief_ready")
        prep.write_stage(3, 2026, 5, "published")
        self.assertEqual(prep.write_stage(3, 2026, 5, "brief_ready")["stage"], "published")

    @patch.object(prep.sync_week_results, "_resolve_week", return_value=0)
    def test_preseason_is_skipped(self, _resolve):
        code, details = prep.main(["--league-id", "3", "--season", "2026"])
        self.assertEqual((code, details["status"]), (0, "skipped"))


if __name__ == "__main__":
    unittest.main()
