import sqlite3

from tests.test_api import ApiTestCase


class TestExposureApi(ApiTestCase):
    """Extends the base single-league seed (tests/test_api.py) with a second
    active league and an inactive third league, to exercise cross-league
    aggregation and the active-leagues-only filter."""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._seed_exposure(conn)
        conn.close()

    def _seed_exposure(self, conn):
        # League Two: active, Keith's team (5) + a rival team (6).
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (2, 'League Two', 'yahoo', 2, 1)"
        )
        conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine, draft_position) VALUES (5, 2, 'My Team Two', 1, 1)"
        )
        conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine, draft_position) VALUES (6, 2, 'Rival Two', 0, 2)"
        )

        # League Three: inactive — Keith's rostered players here must not count.
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (3, 'Inactive League', 'espn', 1, 0)"
        )
        conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine, draft_position) VALUES (7, 3, 'My Team Three', 1, 1)"
        )

        # Team 1 (league 1, mine): Josh Allen (QB/BUF), Saquon Barkley (RB/PHI).
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 1)")
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, 2)")
        # Team 5 (league 2, mine): Saquon again (cross-league exposure) + Bijan (RB/ATL).
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (5, 2)")
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (5, 3)")
        # Team 6 (league 2, NOT mine): Bijan too — must not count toward exposure.
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (6, 3)")
        # Team 7 (league 3, mine, but inactive league): Josh Allen — must not count.
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (7, 1)")

        # Teams with no rostered players at all, for the zero-exposure list.
        conn.execute("INSERT INTO nfl_team_byes (season, team, bye_week) VALUES (2026, 'KC', 10)")
        conn.execute("INSERT INTO nfl_team_byes (season, team, bye_week) VALUES (2026, 'DAL', 9)")
        conn.commit()

    def test_active_league_count_excludes_inactive(self):
        resp = self.client.get("/api/exposure")
        self.assertEqual(resp.get_json()["active_league_count"], 2)

    def test_player_rostered_in_two_active_leagues(self):
        resp = self.client.get("/api/exposure")
        rbs = resp.get_json()["players_by_position"]["RB"]
        saquon = next(p for p in rbs if p["full_name"] == "Saquon Barkley")
        self.assertEqual(saquon["league_count"], 2)
        self.assertEqual(saquon["leagues"], ["League Two", "Test League"])

    def test_single_league_player_still_included(self):
        resp = self.client.get("/api/exposure")
        rbs = resp.get_json()["players_by_position"]["RB"]
        bijan = next(p for p in rbs if p["full_name"] == "Bijan Robinson")
        self.assertEqual(bijan["league_count"], 1)
        self.assertEqual(bijan["leagues"], ["League Two"])

    def test_inactive_league_roster_not_counted(self):
        resp = self.client.get("/api/exposure")
        qbs = resp.get_json()["players_by_position"]["QB"]
        allen = next(p for p in qbs if p["full_name"] == "Josh Allen")
        self.assertEqual(allen["league_count"], 1)
        self.assertEqual(allen["leagues"], ["Test League"])

    def test_non_mine_team_roster_not_counted(self):
        # Bijan is on a rival (non-mine) team in league 2 too, but that must not
        # inflate his league_count beyond the one team Keith actually owns him on.
        resp = self.client.get("/api/exposure")
        rbs = resp.get_json()["players_by_position"]["RB"]
        bijan = next(p for p in rbs if p["full_name"] == "Bijan Robinson")
        self.assertEqual(bijan["league_count"], 1)

    def test_nfl_team_roster_spot_count_vs_unique_players(self):
        resp = self.client.get("/api/exposure")
        nfl_teams = {t["nfl_team"]: t for t in resp.get_json()["nfl_teams"]}

        # Saquon (PHI) owned in 2 leagues -> 2 roster spots, but only 1 unique player.
        self.assertEqual(nfl_teams["PHI"]["roster_spot_count"], 2)
        self.assertEqual(nfl_teams["PHI"]["unique_player_count"], 1)

        # Josh Allen (BUF) owned in 1 active league.
        self.assertEqual(nfl_teams["BUF"]["roster_spot_count"], 1)
        self.assertEqual(nfl_teams["BUF"]["unique_player_count"], 1)
        self.assertEqual(nfl_teams["BUF"]["bye_week"], 7)

        self.assertEqual(nfl_teams["ATL"]["roster_spot_count"], 1)
        self.assertEqual(nfl_teams["ATL"]["unique_player_count"], 1)

    def test_nfl_team_lists_its_players(self):
        resp = self.client.get("/api/exposure")
        nfl_teams = {t["nfl_team"]: t for t in resp.get_json()["nfl_teams"]}

        phi_players = nfl_teams["PHI"]["players"]
        self.assertEqual(len(phi_players), 1)
        self.assertEqual(phi_players[0]["full_name"], "Saquon Barkley")
        self.assertEqual(phi_players[0]["league_count"], 2)

    def test_zero_exposure_teams_lists_unrostered_teams(self):
        resp = self.client.get("/api/exposure")
        zero_exposure = resp.get_json()["zero_exposure_teams"]

        self.assertIn("KC", zero_exposure)
        self.assertIn("DAL", zero_exposure)
        self.assertNotIn("BUF", zero_exposure)  # rostered (Josh Allen)
