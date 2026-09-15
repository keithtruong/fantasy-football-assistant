import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.guillotine import compute_week_result, save_team_snapshot, sync_and_fill_week

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestSaveTeamSnapshot(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) "
            "VALUES (10, 'Guillotine 2026', 'yahoo', 3, 1)"
        )
        self.conn.commit()

    def test_inserts_one_row_per_team(self):
        save_team_snapshot(
            self.conn, 10, 2026, 1,
            [
                {"platform_team_id": "1", "team_name": "A", "points_for": 100.0},
                {"platform_team_id": "2", "team_name": "B", "points_for": 90.0},
            ],
        )
        rows = self.conn.execute("SELECT * FROM guillotine_team_snapshots WHERE league_id = 10").fetchall()
        self.assertEqual(len(rows), 2)

    def test_replaces_not_duplicates_on_rerun(self):
        save_team_snapshot(self.conn, 10, 2026, 1, [{"platform_team_id": "1", "team_name": "A", "points_for": 100.0}])
        save_team_snapshot(self.conn, 10, 2026, 1, [{"platform_team_id": "1", "team_name": "A", "points_for": 105.0}])
        rows = self.conn.execute("SELECT * FROM guillotine_team_snapshots WHERE league_id = 10").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cumulative_points_for"], 105.0)


class TestComputeWeekResult(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) "
            "VALUES (10, 'Guillotine 2026', 'yahoo', 3, 1)"
        )
        self.conn.commit()

    def _snap(self, week, rows):
        save_team_snapshot(self.conn, 10, 2026, week, rows)

    def test_week_one_uses_raw_cumulative_as_the_score(self):
        self._snap(1, [
            {"platform_team_id": "1", "team_name": "A", "points_for": 92.18},
            {"platform_team_id": "2", "team_name": "B", "points_for": 135.3},
            {"platform_team_id": "3", "team_name": "C", "points_for": 54.02},
        ])
        result = compute_week_result(self.conn, 10, 2026, 1, "1")
        self.assertEqual(result, {
            "points_for": 92.18,
            "eliminated_points": 54.02,
            "rank": 2,
            "remaining_count": 3,
        })

    def test_week_two_derives_delta_and_drops_prior_low_scorer(self):
        self._snap(1, [
            {"platform_team_id": "1", "team_name": "A", "points_for": 92.18},
            {"platform_team_id": "2", "team_name": "B", "points_for": 135.3},
            {"platform_team_id": "3", "team_name": "C", "points_for": 54.02},
        ])
        # Week 2: team 3 (last week's low scorer) is gone from the field even
        # though its snapshot data might still be lingering in Yahoo's own
        # standings() -- team 1 scores 60 this week (60 - 0 baseline isn't
        # right; use cumulative totals), team 2 scores less than team 1.
        self._snap(2, [
            {"platform_team_id": "1", "team_name": "A", "points_for": 92.18 + 100.0},
            {"platform_team_id": "2", "team_name": "B", "points_for": 135.3 + 80.0},
            {"platform_team_id": "3", "team_name": "C", "points_for": 54.02 + 999.0},  # eliminated -- must be ignored
        ])
        result = compute_week_result(self.conn, 10, 2026, 2, "1")
        self.assertEqual(result, {
            "points_for": 100.0,
            "eliminated_points": 80.0,
            "rank": 1,
            "remaining_count": 2,
        })

    def test_returns_none_when_a_needed_week_snapshot_is_missing(self):
        self._snap(2, [{"platform_team_id": "1", "team_name": "A", "points_for": 92.18}])
        result = compute_week_result(self.conn, 10, 2026, 2, "1")
        self.assertIsNone(result)  # week 1 was never snapshotted

    def test_returns_none_when_team_already_eliminated(self):
        self._snap(1, [
            {"platform_team_id": "1", "team_name": "A", "points_for": 92.18},
            {"platform_team_id": "2", "team_name": "B", "points_for": 135.3},
            {"platform_team_id": "3", "team_name": "C", "points_for": 54.02},
        ])
        self._snap(2, [
            {"platform_team_id": "1", "team_name": "A", "points_for": 192.18},
            {"platform_team_id": "2", "team_name": "B", "points_for": 215.3},
            {"platform_team_id": "3", "team_name": "C", "points_for": 954.02},
        ])
        result = compute_week_result(self.conn, 10, 2026, 2, "3")
        self.assertIsNone(result)  # team 3 was eliminated after week 1


class TestSyncAndFillWeek(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO league_history (league_history_id, name, active, format) "
            "VALUES (1, 'Guillotine', 1, 'guillotine')"
        )
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (10, 'Guillotine 2026', 'yahoo', '470.l.124095', 3, 1)"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name, is_mine) "
            "VALUES (100, 10, '1', 'Mine', 1)"
        )
        self.conn.commit()

    @patch("ffassistant.guillotine.get_standings")
    def test_fills_week_one_from_live_standings(self, mock_get_standings):
        mock_get_standings.return_value = [
            {"platform_team_id": "1", "team_name": "Mine", "points_for": 92.18},
            {"platform_team_id": "2", "team_name": "Other", "points_for": 54.02},
        ]

        results = sync_and_fill_week(self.conn, 2026, 1)

        self.assertEqual(results, [{
            "league_history_name": "Guillotine",
            "status": "filled",
            "league_history_id": 1,
            "season": 2026,
            "week": 1,
            "points_for": 92.18,
            "eliminated_points": 54.02,
            "rank": 1,
            "remaining_count": 2,
        }])
        stored = self.conn.execute("SELECT * FROM guillotine_weeks WHERE league_history_id = 1").fetchone()
        self.assertEqual(stored["rank"], 1)
        mock_get_standings.assert_called_once_with("470.l.124095")

    @patch("ffassistant.guillotine.get_standings")
    def test_skips_when_no_team_flagged_is_mine(self, mock_get_standings):
        self.conn.execute("DELETE FROM teams")
        self.conn.commit()
        mock_get_standings.return_value = []

        results = sync_and_fill_week(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "Guillotine", "status": "no_my_team_flagged"}])

    def test_skips_league_with_no_matching_platform_league_this_season(self):
        results = sync_and_fill_week(self.conn, 2099, 1)
        self.assertEqual(results, [{"league_history_name": "Guillotine", "status": "no_platform_match"}])

    def test_skips_non_yahoo_platform(self):
        self.conn.execute("UPDATE leagues SET platform = 'espn' WHERE league_id = 10")
        self.conn.commit()

        results = sync_and_fill_week(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "Guillotine", "status": "unsupported_platform"}])

    def test_ignores_non_guillotine_league_history(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name, active) VALUES (2, 'BC1', 1)")
        self.conn.commit()

        with patch("ffassistant.guillotine.get_standings", return_value=[]):
            results = sync_and_fill_week(self.conn, 2026, 1)

        names = [r["league_history_name"] for r in results]
        self.assertEqual(names, ["Guillotine"])  # BC1 (head-to-head) never touched


if __name__ == "__main__":
    unittest.main()
