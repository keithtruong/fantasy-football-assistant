import sqlite3
from unittest.mock import patch

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


class TestStartersExposureApi(TestExposureApi):
    """Builds on TestExposureApi's two-active-league seed, adding
    roster_status values and a current-week opponent pairing in league 1."""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # League 1 (mine, team 1): Josh Allen starts, Saquon sits on my bench.
        conn.execute("UPDATE roster_spots SET roster_status = 'starter' WHERE team_id = 1 AND player_id = 1")
        conn.execute("UPDATE roster_spots SET roster_status = 'bench' WHERE team_id = 1 AND player_id = 2")
        # League 1's team 2 is my current-week opponent, starting Bijan.
        conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (2, 3, 'starter')")
        conn.execute(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (1, 2026, 3, 1, 2)"
        )
        # League 2 (mine, team 5): Saquon starts here -- a different roster_status
        # per team_id is expected (same player, different team).
        conn.execute("UPDATE roster_spots SET roster_status = 'starter' WHERE team_id = 5 AND player_id = 2")
        # Bijan on the rival (non-mine) team 6 in league 2 -- must never count,
        # won by neither "mine" nor "opponent" (no matchup row involves team 6).
        conn.execute("UPDATE roster_spots SET roster_status = 'starter' WHERE team_id = 6 AND player_id = 3")
        conn.commit()
        conn.close()

    def _get(self):
        with patch("ffassistant.api.exposure.smart_current_week", return_value=3):
            return self.client.get("/api/exposure/starters")

    def test_my_starters_excludes_bench(self):
        resp = self._get()
        data = resp.get_json()
        self.assertEqual(data["week"], 3)
        qb_names = [p["full_name"] for p in data["my_starters_by_position"]["QB"]]
        self.assertIn("Josh Allen", qb_names)

    def test_my_starters_aggregates_across_leagues_excluding_bench_leagues(self):
        # Saquon starts on team 5 (League Two) but sits on my bench on team 1
        # (Test League) -- only the league where he actually started counts.
        resp = self._get()
        rbs = resp.get_json()["my_starters_by_position"]["RB"]
        saquon = next(p for p in rbs if p["full_name"] == "Saquon Barkley")
        self.assertEqual(saquon["league_count"], 1)
        self.assertEqual(saquon["leagues"], ["League Two"])

    def test_opponent_starters_come_from_current_week_matchup(self):
        resp = self._get()
        rbs = resp.get_json()["opponent_starters_by_position"]["RB"]
        names = [p["full_name"] for p in rbs]
        self.assertIn("Bijan Robinson", names)  # team 2's starter, my week-3 opponent

    def test_exclusivity_sole_starter_when_no_opponent_starts_it(self):
        resp = self._get()
        qbs = resp.get_json()["my_starters_by_position"]["QB"]
        allen = next(p for p in qbs if p["full_name"] == "Josh Allen")
        self.assertEqual(allen["exclusivity"], "sole_starter")

    def test_exclusivity_no_shares_when_i_dont_start_it(self):
        resp = self._get()
        rbs = resp.get_json()["opponent_starters_by_position"]["RB"]
        bijan = next(p for p in rbs if p["full_name"] == "Bijan Robinson")
        self.assertEqual(bijan["exclusivity"], "no_shares")

    def test_rival_team_with_no_matchup_row_is_excluded(self):
        # Team 6 (league 2) starts Bijan too, but has no weekly_matchups row
        # pairing it with any of my teams -- must not appear as an opponent.
        resp = self._get()
        rbs = resp.get_json()["opponent_starters_by_position"]["RB"]
        bijan = next(p for p in rbs if p["full_name"] == "Bijan Robinson")
        self.assertEqual(bijan["league_count"], 1)  # only via league 1's matchup, not league 2

    def test_quiet_nfl_teams_excludes_started_teams_but_includes_unrostered(self):
        resp = self._get()
        quiet = resp.get_json()["quiet_nfl_teams"]
        self.assertIn("KC", quiet)
        self.assertIn("DAL", quiet)
        self.assertNotIn("BUF", quiet)  # Josh Allen starts for me
        self.assertNotIn("ATL", quiet)  # Bijan starts for my opponent

    def test_null_week_when_current_week_unresolvable(self):
        with patch("ffassistant.api.exposure.smart_current_week", return_value=None):
            resp = self.client.get("/api/exposure/starters")
        data = resp.get_json()
        self.assertIsNone(data["week"])
        # My own starters still resolve fine -- only the opponent side needs a week.
        qb_names = [p["full_name"] for p in data["my_starters_by_position"]["QB"]]
        self.assertIn("Josh Allen", qb_names)
        self.assertEqual(data["opponent_starters_by_position"]["RB"], [])

    def test_by_nfl_team_root_for_when_only_mine(self):
        resp = self._get()
        teams = {t["nfl_team"]: t for t in resp.get_json()["starters_by_nfl_team"]}
        self.assertEqual(teams["BUF"]["verdict"], "root_for")  # Josh Allen, mine only
        self.assertEqual(teams["BUF"]["my_count"], 1)
        self.assertEqual(teams["BUF"]["opponent_count"], 0)
        self.assertEqual([p["full_name"] for p in teams["BUF"]["my_players"]], ["Josh Allen"])
        self.assertEqual(teams["BUF"]["opponent_players"], [])

    def test_by_nfl_team_mixed_when_both_sides_start_it(self):
        # A brand-new player/team (not touched by any season-long exposure
        # fixture) so this test's extra seeding can't bleed into those
        # assertions: I start a KC player on team 1, my week-3 opponent
        # (team 2) starts a different KC player -- split rooting interest.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (4, 'My KC Guy', 'WR', 'KC')")
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (5, 'Their KC Guy', 'WR', 'KC')")
        conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (1, 4, 'starter')")
        conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (2, 5, 'starter')")
        conn.commit()
        conn.close()

        resp = self._get()
        teams = {t["nfl_team"]: t for t in resp.get_json()["starters_by_nfl_team"]}
        self.assertEqual(teams["KC"]["verdict"], "mixed")
        self.assertEqual(teams["KC"]["my_count"], 1)
        self.assertEqual(teams["KC"]["opponent_count"], 1)
        self.assertEqual([p["full_name"] for p in teams["KC"]["my_players"]], ["My KC Guy"])
        self.assertEqual([p["full_name"] for p in teams["KC"]["opponent_players"]], ["Their KC Guy"])

    def test_exclusivity_null_when_same_player_id_starts_both_sides(self):
        # A shared keeper/dynasty-style edge case: the exact same player_id
        # starting for both me and an opponent (e.g. two different leagues'
        # teams that happen to be the same real person) is neither exclusive
        # to me nor to the opponent -- exclusivity must be None on both sides.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (4, 'Shared Guy', 'WR', 'KC')")
        conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (1, 4, 'starter')")
        conn.execute("INSERT INTO roster_spots (team_id, player_id, roster_status) VALUES (2, 4, 'starter')")
        conn.commit()
        conn.close()

        resp = self._get()
        my_wr = next(p for p in resp.get_json()["my_starters_by_position"]["WR"] if p["full_name"] == "Shared Guy")
        opp_wr = next(p for p in resp.get_json()["opponent_starters_by_position"]["WR"] if p["full_name"] == "Shared Guy")
        self.assertIsNone(my_wr["exclusivity"])
        self.assertIsNone(opp_wr["exclusivity"])

    def test_by_nfl_team_excludes_teams_with_no_starters_either_side(self):
        resp = self._get()
        team_names = {t["nfl_team"] for t in resp.get_json()["starters_by_nfl_team"]}
        self.assertIn("KC", resp.get_json()["quiet_nfl_teams"])
        self.assertNotIn("KC", team_names)

    def test_by_nfl_team_sorted_by_total_involvement_descending(self):
        resp = self._get()
        teams = resp.get_json()["starters_by_nfl_team"]
        totals = [t["my_count"] + t["opponent_count"] for t in teams]
        self.assertEqual(totals, sorted(totals, reverse=True))
