from tests.test_api import ApiTestCase

SEASON = 2026
WEEK = 5


class InSeasonTestCase(ApiTestCase):
    def _seed_in_season(self, conn):
        # Team 1 is "mine" (from ApiTestCase._seed). Roster: Saquon Barkley (ranked,
        # questionable) + an unranked RB (simulates injured/unranked-but-rostered).
        conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (4, 'Unranked RB Guy', 'RB', 'NYJ')"
        )
        conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (5, 'Great Available RB', 'RB', 'KC')"
        )
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 2)")  # Saquon -> mine
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 4)")  # Unranked RB -> mine
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (2, 3)")  # Bijan -> rival team

        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, rank) VALUES (2, 'weekly', ?, ?, 20)",
            (SEASON, WEEK),
        )
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, rank) VALUES (3, 'weekly', ?, ?, 5)",
            (SEASON, WEEK),
        )
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, rank) VALUES (5, 'weekly', ?, ?, 3)",
            (SEASON, WEEK),
        )
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, rank) VALUES (1, 'weekly', ?, ?, 8)",
            (SEASON, WEEK),
        )
        conn.execute(
            "INSERT INTO player_status (player_id, season, week, status, source) VALUES (2, ?, ?, 'questionable', 'sleeper')",
            (SEASON, WEEK),
        )
        conn.commit()


class TestInSeasonWeeklyView(InSeasonTestCase):
    def setUp(self):
        super().setUp()
        conn = self._connect_for_seeding()
        self._seed_in_season(conn)
        conn.close()

    def _connect_for_seeding(self):
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_requires_week_for_weekly_view(self):
        resp = self.client.get("/api/leagues/1/in_season?view=weekly&season=2026")
        self.assertEqual(resp.status_code, 400)

    def test_rostered_sorts_worst_first_with_unranked_on_top(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        rb_rostered = data["RB"]["rostered"]
        self.assertEqual([p["full_name"] for p in rb_rostered], ["Unranked RB Guy", "Saquon Barkley"])
        self.assertIsNone(rb_rostered[0]["rank"])
        self.assertEqual(rb_rostered[1]["rank"], 20)

    def test_rostered_includes_status(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        saquon = next(p for p in data["RB"]["rostered"] if p["full_name"] == "Saquon Barkley")
        self.assertEqual(saquon["status"], "questionable")

    def test_available_excludes_players_rostered_by_any_team(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        available_names = [p["full_name"] for p in data["RB"]["available"]]
        self.assertNotIn("Bijan Robinson", available_names)  # rostered by rival team, not mine
        self.assertIn("Great Available RB", available_names)

    def test_available_sorted_best_first(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        ranks = [p["rank"] for p in data["RB"]["available"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_beats_worst_rostered_true_when_unranked_rostered_exists(self):
        # RB has an unranked rostered player -> every available RB auto-beats it.
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        for player in data["RB"]["available"]:
            self.assertTrue(player["beats_worst_rostered"])

    def test_beats_worst_rostered_false_when_no_rostered_players_at_position(self):
        # No QB rostered at all -> nothing to beat.
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        self.assertEqual(data["QB"]["rostered"], [])
        for player in data["QB"]["available"]:
            self.assertFalse(player["beats_worst_rostered"])

    def test_weekly_view_includes_dst_and_k_positions(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        data = resp.get_json()
        self.assertIn("DST", data)
        self.assertIn("K", data)

    def test_requires_my_team_to_be_set(self):
        conn = self._connect_for_seeding()
        conn.execute("UPDATE teams SET is_mine = 0 WHERE league_id = 1")
        conn.commit()
        conn.close()

        resp = self.client.get(f"/api/leagues/1/in_season?view=weekly&season={SEASON}&week={WEEK}")
        self.assertEqual(resp.status_code, 400)


class TestInSeasonRosView(InSeasonTestCase):
    def setUp(self):
        super().setUp()
        conn = self._connect_for_seeding()
        self._seed_in_season(conn)
        # ROS rankings: no week, per schema convention.
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, rank) VALUES (5, 'ros', ?, NULL, 4)",
            (SEASON,),
        )
        conn.commit()
        conn.close()

    def _connect_for_seeding(self):
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_ros_excludes_dst_and_k(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=ros&season={SEASON}")
        data = resp.get_json()
        self.assertNotIn("DST", data)
        self.assertNotIn("K", data)
        self.assertIn("RB", data)

    def test_ros_does_not_require_week(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=ros&season={SEASON}")
        self.assertEqual(resp.status_code, 200)

    def test_ros_available_uses_ros_rankings(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=ros&season={SEASON}")
        data = resp.get_json()
        names = [p["full_name"] for p in data["RB"]["available"]]
        self.assertIn("Great Available RB", names)


if __name__ == "__main__":
    import unittest

    unittest.main()
