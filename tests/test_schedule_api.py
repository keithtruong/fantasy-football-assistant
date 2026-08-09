import sqlite3
import unittest

from ffassistant.api.schedule import difficulty_for_rank
from tests.test_api import ApiTestCase


class TestDifficultyForRank(unittest.TestCase):
    """Pure ranking logic, independent of DB setup — mirrors draft.js's
    top/bottom-8-of-32 Hard/Easy SOS convention."""

    def test_top_8_of_32_is_hard(self):
        self.assertEqual(difficulty_for_rank(1, 32), "hard")
        self.assertEqual(difficulty_for_rank(8, 32), "hard")

    def test_bottom_8_of_32_is_easy(self):
        self.assertEqual(difficulty_for_rank(25, 32), "easy")
        self.assertEqual(difficulty_for_rank(32, 32), "easy")

    def test_middle_of_32_is_neutral(self):
        self.assertIsNone(difficulty_for_rank(9, 32))
        self.assertIsNone(difficulty_for_rank(24, 32))

    def test_small_team_count_still_bounds_correctly(self):
        # 12 teams: ranks 1-8 -> hard, only 9-12 have room left for "easy".
        self.assertEqual(difficulty_for_rank(8, 12), "hard")
        self.assertEqual(difficulty_for_rank(9, 12), "easy")


class TestScheduleApi(ApiTestCase):
    """Extends the base single-league seed (tests/test_api.py), which already
    seeds nfl_team_byes with BUF/7 for season 2026."""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._seed_schedule(conn)
        conn.close()

    def _seed_schedule(self, conn):
        conn.execute("INSERT INTO nfl_team_byes (season, team, bye_week) VALUES (2026, 'PHI', 10)")
        conn.execute("INSERT INTO nfl_team_byes (season, team, bye_week) VALUES (2026, 'ATL', 11)")

        # Win totals: PHI highest (toughest opponent), ATL lowest (easiest).
        # 8 filler teams pad the field to 11 total, so ATL's last-place rank
        # (11) clears the "rank > total - NOTABLE_RANK" easy threshold without
        # also tripping the "rank <= NOTABLE_RANK" hard check first.
        conn.execute(
            "INSERT INTO nfl_team_playoff_sos (season, team, own_implied_wins) VALUES (2026, 'BUF', 7.0)"
        )
        conn.execute(
            "INSERT INTO nfl_team_playoff_sos (season, team, own_implied_wins) VALUES (2026, 'PHI', 12.0)"
        )
        conn.execute(
            "INSERT INTO nfl_team_playoff_sos (season, team, own_implied_wins) VALUES (2026, 'ATL', 2.0)"
        )
        for team, wins in [("KC", 11.0), ("SF", 10.0), ("DAL", 9.0), ("GB", 8.0),
                            ("MIA", 6.0), ("DEN", 5.0), ("SEA", 4.0), ("NYG", 3.0)]:
            conn.execute(
                "INSERT INTO nfl_team_playoff_sos (season, team, own_implied_wins) VALUES (2026, ?, ?)",
                (team, wins),
            )

        # BUF hosts PHI in week 1 (tough matchup), plays at ATL in week 2 (easy matchup).
        conn.execute(
            "INSERT INTO nfl_team_schedule (season, team, week, opponent, is_home) VALUES (2026, 'BUF', 1, 'PHI', 1)"
        )
        conn.execute(
            "INSERT INTO nfl_team_schedule (season, team, week, opponent, is_home) VALUES (2026, 'BUF', 2, 'ATL', 0)"
        )
        conn.commit()

    def test_bye_week_marked(self):
        resp = self.client.get("/api/schedule?season=2026")
        teams = {t["team"]: t for t in resp.get_json()["teams"]}
        self.assertEqual(teams["BUF"]["weeks"][6], {"bye": True})  # week 7 -> index 6

    def test_home_game_has_no_at_prefix_marker(self):
        resp = self.client.get("/api/schedule?season=2026")
        teams = {t["team"]: t for t in resp.get_json()["teams"]}
        week1 = teams["BUF"]["weeks"][0]
        self.assertEqual(week1["opponent"], "PHI")
        self.assertTrue(week1["is_home"])

    def test_away_game_flagged(self):
        resp = self.client.get("/api/schedule?season=2026")
        teams = {t["team"]: t for t in resp.get_json()["teams"]}
        week2 = teams["BUF"]["weeks"][1]
        self.assertEqual(week2["opponent"], "ATL")
        self.assertFalse(week2["is_home"])

    def test_tough_opponent_marked_hard(self):
        # PHI (12.0) is rank 1 of 11 -> within top NOTABLE_RANK -> hard.
        resp = self.client.get("/api/schedule?season=2026")
        teams = {t["team"]: t for t in resp.get_json()["teams"]}
        self.assertEqual(teams["BUF"]["weeks"][0]["difficulty"], "hard")

    def test_easy_opponent_marked_easy(self):
        # ATL (2.0) is rank 11 of 11 (last place) -> within bottom NOTABLE_RANK -> easy.
        resp = self.client.get("/api/schedule?season=2026")
        teams = {t["team"]: t for t in resp.get_json()["teams"]}
        self.assertEqual(teams["BUF"]["weeks"][1]["difficulty"], "easy")
