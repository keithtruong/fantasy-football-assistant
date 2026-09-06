import datetime
import sqlite3
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
