import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.autofill_wl import _resolve_week

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestResolveWeek(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def test_explicit_week_wins_over_live_lookup(self):
        with patch("scripts.autofill_wl.smart_current_week") as mock_smart:
            week = _resolve_week(self.conn, 2026, 5)
            mock_smart.assert_not_called()
        self.assertEqual(week, 5)

    @patch("scripts.autofill_wl.smart_current_week")
    def test_defaults_to_last_week_when_omitted(self, mock_smart):
        mock_smart.return_value = 3
        week = _resolve_week(self.conn, 2026, None)
        self.assertEqual(week, 2)

    @patch("scripts.autofill_wl.smart_current_week")
    def test_returns_none_when_current_week_is_one(self, mock_smart):
        # Week 1 has no "last week" to autofill yet.
        mock_smart.return_value = 1
        week = _resolve_week(self.conn, 2026, None)
        self.assertIsNone(week)

    @patch("scripts.autofill_wl.smart_current_week")
    def test_returns_none_when_live_lookup_unavailable(self, mock_smart):
        mock_smart.return_value = None
        week = _resolve_week(self.conn, 2026, None)
        self.assertIsNone(week)


if __name__ == "__main__":
    unittest.main()
