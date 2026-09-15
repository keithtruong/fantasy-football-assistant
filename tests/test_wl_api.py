import datetime
import sqlite3

from tests.test_api import ApiTestCase


class WlTestCase(ApiTestCase):
    """W-L doesn't touch leagues/teams/players at all — the base seed from
    ApiTestCase is just unused noise here, kept only for the shared
    app/client/db-patching setup, same convention as test_in_season_api.py
    and test_exposure_api.py."""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._seed_wl(conn)
        conn.close()

    def _seed_wl(self, conn):
        conn.execute("INSERT INTO league_history (league_history_id, name, active) VALUES (1, 'Alpha', 1)")
        conn.execute("INSERT INTO league_history (league_history_id, name, active) VALUES (2, 'Beta', 0)")
        conn.execute(
            "INSERT INTO league_history (league_history_id, name, active, format) VALUES (3, 'Gamma', 1, 'guillotine')"
        )

        # Gamma 2025: two weeks survived, then eliminated -- kept out of every
        # head-to-head aggregate by living in guillotine_weeks instead of
        # matchups.
        conn.execute(
            "INSERT INTO guillotine_weeks (league_history_id, season, week, points_for, eliminated_points, rank, remaining_count) "
            "VALUES (3, 2025, 1, 130.0, 90.0, 5, 10)"
        )
        conn.execute(
            "INSERT INTO guillotine_weeks (league_history_id, season, week, points_for, eliminated_points, rank, remaining_count) "
            "VALUES (3, 2025, 2, 85.0, 85.0, 9, 9)"
        )

        # Alpha 2025: two weeks played, one close game.
        conn.execute(
            "INSERT INTO matchups (league_history_id, season, week, points_for, points_against, outcome) "
            "VALUES (1, 2025, 1, 120.0, 100.0, 'W')"
        )
        conn.execute(
            "INSERT INTO matchups (league_history_id, season, week, points_for, points_against, outcome, playoff_round) "
            "VALUES (1, 2025, 2, 95.0, 98.0, 'L', 'semifinal')"
        )
        # Beta 2025: one week, also a loss, to build up the weekly aggregate.
        conn.execute(
            "INSERT INTO matchups (league_history_id, season, week, points_for, points_against, outcome) "
            "VALUES (2, 2025, 1, 80.0, 110.0, 'L')"
        )

        conn.execute(
            "INSERT INTO league_seasons (league_history_id, season, wins, losses, ties, buy_in, max_payout, actual_payout, finish_position) "
            "VALUES (1, 2025, 10, 5, 0, 50, 500, 500, 1)"
        )
        conn.execute(
            "INSERT INTO league_seasons (league_history_id, season, wins, losses, ties, buy_in, max_payout, actual_payout, finish_position) "
            "VALUES (1, 2024, 8, 7, 0, 50, 500, 0, 3)"
        )
        conn.commit()


class TestLeagueHistoryApi(WlTestCase):
    def test_lists_all_leagues(self):
        resp = self.client.get("/api/wl/league_history")
        names = {r["name"]: r["active"] for r in resp.get_json()}
        self.assertEqual(names, {"Alpha": 1, "Beta": 0, "Gamma": 1})


class TestGamesApi(WlTestCase):
    def test_active_league_gets_a_card_even_with_no_rows_that_year(self):
        resp = self.client.get("/api/wl/games?year=2026")
        names = [g["name"] for g in resp.get_json()]
        self.assertIn("Alpha", names)  # active, even with zero 2026 rows
        self.assertNotIn("Beta", names)  # inactive and no 2026 data

        alpha = next(g for g in resp.get_json() if g["name"] == "Alpha")
        self.assertEqual(len(alpha["weeks"]), 18)
        self.assertTrue(all(w["outcome"] is None for w in alpha["weeks"]))

    def test_inactive_league_still_shows_for_a_year_it_has_data(self):
        resp = self.client.get("/api/wl/games?year=2025")
        names = [g["name"] for g in resp.get_json()]
        self.assertIn("Beta", names)

    def test_week_rows_include_differential_and_playoff_round(self):
        resp = self.client.get("/api/wl/games?year=2025")
        alpha = next(g for g in resp.get_json() if g["name"] == "Alpha")
        week2 = next(w for w in alpha["weeks"] if w["week"] == 2)
        self.assertEqual(week2["differential"], 95.0 - 98.0)
        self.assertEqual(week2["playoff_round"], "semifinal")

    def test_totals_aggregate_correctly(self):
        resp = self.client.get("/api/wl/games?year=2025")
        alpha = next(g for g in resp.get_json() if g["name"] == "Alpha")
        self.assertEqual(alpha["totals"]["wins"], 1)
        self.assertEqual(alpha["totals"]["losses"], 1)
        self.assertEqual(alpha["totals"]["points_for"], 215.0)

    def test_guillotine_league_gets_rank_columns_and_final_standing_totals(self):
        resp = self.client.get("/api/wl/games?year=2025")
        gamma = next(g for g in resp.get_json() if g["name"] == "Gamma")
        self.assertEqual(gamma["format"], "guillotine")

        week1 = next(w for w in gamma["weeks"] if w["week"] == 1)
        self.assertEqual(week1["rank"], 5)
        self.assertEqual(week1["remaining_count"], 10)
        self.assertEqual(week1["eliminated_points"], 90.0)
        self.assertNotIn("outcome", week1)

        # Final standing reflects the last week played (week 2: eliminated,
        # 9 of 9), not a summed W/L.
        self.assertEqual(gamma["totals"], {"weeks_played": 2, "final_rank": 9, "final_remaining_count": 9})


class TestWeeklyApi(WlTestCase):
    def test_guillotine_weeks_excluded_from_cross_league_aggregate(self):
        # Gamma's rows live in guillotine_weeks, not matchups, so they never
        # reach this aggregate -- only Alpha (W) and Beta (L) count toward
        # week 1's net.
        resp = self.client.get("/api/wl/weekly?year=2025")
        week1 = next(w for w in resp.get_json() if w["week"] == 1)
        self.assertEqual(week1["net_games_above_even"], 0)

    def test_net_and_cumulative_across_leagues(self):
        resp = self.client.get("/api/wl/weekly?year=2025")
        weeks = resp.get_json()
        week1 = next(w for w in weeks if w["week"] == 1)
        week2 = next(w for w in weeks if w["week"] == 2)

        # Week 1: Alpha W, Beta L -> net 0.
        self.assertEqual(week1["net_games_above_even"], 0)
        self.assertEqual(week1["cumulative_net"], 0)
        # Week 2: Alpha L only -> net -1, cumulative -1.
        self.assertEqual(week2["net_games_above_even"], -1)
        self.assertEqual(week2["cumulative_net"], -1)


class TestLeaguesViewApi(WlTestCase):
    def test_returns_season_row_fields(self):
        resp = self.client.get("/api/wl/leagues?year=2025")
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Alpha")
        self.assertEqual(data[0]["wins"], 10)
        self.assertEqual(data[0]["finish_position"], 1)


class TestCloseGamesApi(WlTestCase):
    def test_filters_by_margin_and_sorts_ascending(self):
        resp = self.client.get("/api/wl/close_games?year=2025")
        data = resp.get_json()
        # Alpha week1 margin=20 (excluded), Alpha week2 margin=3 (included),
        # Beta week1 margin=30 (excluded), Gamma week2 margin=0 (excluded --
        # it's a guillotine elimination-vs-my-score gap, not a real matchup,
        # and lives in guillotine_weeks so this query never sees it).
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["league_name"], "Alpha")
        self.assertEqual(data[0]["week"], 2)
        self.assertAlmostEqual(data[0]["margin"], 3.0)


class TestAllTimeApi(WlTestCase):
    def test_aggregates_across_seasons_and_finish_counts(self):
        resp = self.client.get("/api/wl/all_time")
        alpha = next(r for r in resp.get_json() if r["name"] == "Alpha")
        self.assertEqual(alpha["wins"], 18)  # 10 + 8
        self.assertEqual(alpha["losses"], 12)  # 5 + 7
        self.assertEqual(alpha["years_played"], 2)
        self.assertEqual(alpha["firsts"], 1)
        self.assertEqual(alpha["thirds"], 1)
        self.assertEqual(alpha["first_years"], [2025])
        self.assertEqual(alpha["second_years"], [])
        self.assertEqual(alpha["third_years"], [2024])
        self.assertAlmostEqual(alpha["win_pct"], 18 / 30)
        # PF/PA summed from matchups (only 2025 has any matchup rows seeded).
        self.assertEqual(alpha["points_for"], 215.0)
        # Buy-in/payout summed across both seeded seasons (2025: 50/500, 2024: 50/0).
        self.assertEqual(alpha["total_buy_in"], 100)
        self.assertEqual(alpha["total_actual_payout"], 500)

    def test_league_with_no_seasons_has_null_win_pct(self):
        resp = self.client.get("/api/wl/all_time")
        beta = next(r for r in resp.get_json() if r["name"] == "Beta")
        self.assertEqual(beta["years_played"], 0)
        self.assertIsNone(beta["win_pct"])


class TestFinishesApi(WlTestCase):
    def test_years_span_data_range_through_current_year(self):
        resp = self.client.get("/api/wl/finishes")
        data = resp.get_json()
        current_year = datetime.date.today().year
        self.assertEqual(data["years"], list(range(2024, current_year + 1)))

    def test_finish_grid_by_league_and_year(self):
        resp = self.client.get("/api/wl/finishes")
        data = resp.get_json()
        alpha = next(l for l in data["leagues"] if l["name"] == "Alpha")
        beta = next(l for l in data["leagues"] if l["name"] == "Beta")

        self.assertEqual(alpha["finishes"]["2024"], 3)
        self.assertEqual(alpha["finishes"]["2025"], 1)
        # Beta has no league_seasons rows at all -- every year is null.
        self.assertTrue(all(v is None for v in beta["finishes"].values()))


class TestPutMatchupApi(WlTestCase):
    def test_insert_derives_outcome_from_scores(self):
        resp = self.client.put(
            "/api/wl/matchups",
            json={"league_history_id": 1, "season": 2026, "week": 1, "points_for": 100.0, "points_against": 90.0},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["outcome"], "W")

        games = self.client.get("/api/wl/games?year=2026").get_json()
        alpha = next(g for g in games if g["name"] == "Alpha")
        week1 = next(w for w in alpha["weeks"] if w["week"] == 1)
        self.assertEqual(week1["outcome"], "W")

    def test_tie_derived_when_scores_equal(self):
        resp = self.client.put(
            "/api/wl/matchups",
            json={"league_history_id": 1, "season": 2026, "week": 2, "points_for": 100.0, "points_against": 100.0},
        )
        self.assertEqual(resp.get_json()["outcome"], "T")

    def test_overwrite_upserts_not_duplicates(self):
        self.client.put(
            "/api/wl/matchups",
            json={"league_history_id": 1, "season": 2026, "week": 1, "points_for": 100.0, "points_against": 90.0},
        )
        self.client.put(
            "/api/wl/matchups",
            json={"league_history_id": 1, "season": 2026, "week": 1, "points_for": 80.0, "points_against": 90.0},
        )
        games = self.client.get("/api/wl/games?year=2026").get_json()
        alpha = next(g for g in games if g["name"] == "Alpha")
        week1_rows = [w for w in alpha["weeks"] if w["week"] == 1]
        self.assertEqual(len(week1_rows), 1)
        self.assertEqual(week1_rows[0]["outcome"], "L")

    def test_rejects_missing_scores(self):
        resp = self.client.put(
            "/api/wl/matchups",
            json={"league_history_id": 1, "season": 2026, "week": 1},
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_invalid_playoff_round(self):
        resp = self.client.put(
            "/api/wl/matchups",
            json={
                "league_history_id": 1, "season": 2026, "week": 1,
                "points_for": 100.0, "points_against": 90.0, "playoff_round": "bogus",
            },
        )
        self.assertEqual(resp.status_code, 400)


class TestPutGuillotineWeekApi(WlTestCase):
    def test_insert_stores_rank_and_eliminated_score(self):
        resp = self.client.put(
            "/api/wl/guillotine_weeks",
            json={
                "league_history_id": 3, "season": 2026, "week": 1,
                "points_for": 140.0, "eliminated_points": 75.0, "rank": 4, "remaining_count": 10,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["rank"], 4)

        games = self.client.get("/api/wl/games?year=2026").get_json()
        gamma = next(g for g in games if g["name"] == "Gamma")
        week1 = next(w for w in gamma["weeks"] if w["week"] == 1)
        self.assertEqual(week1["rank"], 4)
        self.assertEqual(week1["eliminated_points"], 75.0)

    def test_overwrite_upserts_not_duplicates(self):
        self.client.put(
            "/api/wl/guillotine_weeks",
            json={
                "league_history_id": 3, "season": 2026, "week": 1,
                "points_for": 140.0, "eliminated_points": 75.0, "rank": 4, "remaining_count": 10,
            },
        )
        self.client.put(
            "/api/wl/guillotine_weeks",
            json={
                "league_history_id": 3, "season": 2026, "week": 1,
                "points_for": 130.0, "eliminated_points": 78.0, "rank": 3, "remaining_count": 9,
            },
        )
        games = self.client.get("/api/wl/games?year=2026").get_json()
        gamma = next(g for g in games if g["name"] == "Gamma")
        week1_rows = [w for w in gamma["weeks"] if w["week"] == 1 and w["rank"] is not None]
        self.assertEqual(len(week1_rows), 1)
        self.assertEqual(week1_rows[0]["rank"], 3)

    def test_rejects_missing_fields(self):
        resp = self.client.put(
            "/api/wl/guillotine_weeks",
            json={"league_history_id": 3, "season": 2026, "week": 1},
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_rank_greater_than_remaining_count(self):
        resp = self.client.put(
            "/api/wl/guillotine_weeks",
            json={
                "league_history_id": 3, "season": 2026, "week": 1,
                "points_for": 140.0, "eliminated_points": 75.0, "rank": 11, "remaining_count": 10,
            },
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    import unittest

    unittest.main()
