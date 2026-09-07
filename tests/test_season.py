import datetime
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant import season

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


class TestCurrentWeek(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())

    def tearDown(self):
        self.conn.close()

    def test_none_when_week1_start_date_not_set(self):
        self.assertIsNone(season.current_week(self.conn, 2026))

    def test_before_week1_returns_none(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        self.assertIsNone(season.current_week(self.conn, 2026, today=datetime.date(2026, 9, 1)))

    def test_week1_start_date_itself_is_week_1(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        self.assertEqual(season.current_week(self.conn, 2026, today=datetime.date(2026, 9, 9)), 1)

    def test_midweek_stays_in_same_week(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        self.assertEqual(season.current_week(self.conn, 2026, today=datetime.date(2026, 9, 14)), 1)

    def test_next_week_boundary(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        self.assertEqual(season.current_week(self.conn, 2026, today=datetime.date(2026, 9, 16)), 2)

    def test_week_17_is_last_valid_week(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        week17_start = datetime.date(2026, 9, 9) + datetime.timedelta(weeks=16)
        self.assertEqual(season.current_week(self.conn, 2026, today=week17_start), 17)

    def test_after_week_17_returns_none(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        week18_start = datetime.date(2026, 9, 9) + datetime.timedelta(weeks=17)
        self.assertIsNone(season.current_week(self.conn, 2026, today=week18_start))

    def test_set_week1_start_date_upserts(self):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 10))
        self.assertEqual(season.get_week1_start_date(self.conn, 2026), datetime.date(2026, 9, 10))


class TestSmartCurrentWeek(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())

    def tearDown(self):
        self.conn.close()

    @patch.object(season, "_fetch_live_week", return_value=7)
    def test_prefers_live_week_over_date_math(self, _mock_live):
        # No week1_start_date configured at all — live alone is enough.
        self.assertEqual(season.smart_current_week(self.conn, 2026), 7)

    @patch.object(season, "_fetch_live_week", return_value=None)
    def test_falls_back_to_current_week_when_live_unavailable(self, _mock_live):
        season.set_week1_start_date(self.conn, 2026, datetime.date(2026, 9, 9))
        with patch.object(season, "current_week", return_value=99) as mock_fallback:
            result = season.smart_current_week(self.conn, 2026)
        self.assertEqual(result, 99)
        mock_fallback.assert_called_once_with(self.conn, 2026)


class TestFetchLiveWeek(unittest.TestCase):
    @patch("ffassistant.connectors.sleeper.get_nfl_state", return_value={"season": "2026", "season_type": "regular", "week": 7})
    def test_returns_week_during_regular_season(self, _mock):
        self.assertEqual(season._fetch_live_week(2026), 7)

    @patch("ffassistant.connectors.sleeper.get_nfl_state", return_value={"season": "2026", "season_type": "pre", "week": 3})
    def test_preseason_defaults_to_week_one(self, _mock):
        # Keith's own call: nothing meaningful to show before the season starts.
        self.assertEqual(season._fetch_live_week(2026), 1)

    @patch("ffassistant.connectors.sleeper.get_nfl_state", return_value={"season": "2025", "season_type": "regular", "week": 7})
    def test_season_mismatch_returns_none(self, _mock):
        # Live state is for a different season than the one being asked about.
        self.assertIsNone(season._fetch_live_week(2026))

    @patch("ffassistant.connectors.sleeper.get_nfl_state", side_effect=RuntimeError("network down"))
    def test_network_failure_returns_none(self, _mock):
        self.assertIsNone(season._fetch_live_week(2026))

    @patch("ffassistant.connectors.sleeper.get_nfl_state", return_value={"season": "2026", "season_type": "post", "week": 19})
    def test_out_of_range_week_returns_none(self, _mock):
        # Postseason week numbering (18+) falls outside this app's fantasy 1-17 range.
        self.assertIsNone(season._fetch_live_week(2026))


if __name__ == "__main__":
    unittest.main()
