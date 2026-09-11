import sqlite3

from tests.test_api import ApiTestCase

SEASON = 2026
WEEK = 5


class TestStartersAllView(ApiTestCase):
    """/api/starters_all — every one of Keith's teams across all active
    leagues, for the Starters tab's all-leagues view. Base seed (ApiTestCase)
    already gives league 1: roster_slots QB=1/RB=2, team 1 "mine", players
    Josh Allen (QB), Saquon Barkley (RB), Bijan Robinson (RB), and rec=1 ->
    full_ppr — this file rosters those players to team 1, adds week-5 weekly
    rankings for them, and seeds a second, independent league.
    """

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._seed_more(conn)
        conn.close()

    def _seed_more(self, conn):
        for player_id in (1, 2, 3):
            conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, ?)", (player_id,))

        for player_id, rank in {1: 3, 2: 1, 3: 2}.items():
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
                "VALUES (?, 'weekly', ?, ?, 'full_ppr', ?, NULL)",
                (player_id, SEASON, WEEK, rank),
            )

        # A second, independent league with its own team/roster/scoring.
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (2, 'Other League', 'espn', 2, 1)"
        )
        conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (10, 2, 'My Other Team', 1)"
        )
        conn.execute("INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (2, 'QB', 1)")
        conn.execute("INSERT INTO league_scoring (league_id, stat_key, points) VALUES (2, 'rec', 0)")  # non_ppr

        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (20, 'Other QB', 'QB', 'MIA')")
        conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (10, 20)")
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
            "VALUES (20, 'weekly', ?, ?, 'non_ppr', 1, NULL)",
            (SEASON, WEEK),
        )

        # A third league with no team marked as Keith's own yet — must be
        # skipped rather than failing the whole request.
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (3, 'Unclaimed League', 'yahoo', 2, 1)"
        )
        conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (11, 3, 'Someone', 0)")

        # An inactive league with an is_mine team — must be excluded too.
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (4, 'Retired League', 'sleeper', 2, 0)"
        )
        conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (12, 4, 'Old Team', 1)")

        conn.commit()

    def test_requires_week(self):
        resp = self.client.get(f"/api/starters_all?season={SEASON}")
        self.assertEqual(resp.status_code, 400)

    def test_returns_one_entry_per_claimed_active_league(self):
        resp = self.client.get(f"/api/starters_all?season={SEASON}&week={WEEK}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        league_ids = {entry["league_id"] for entry in data}
        self.assertEqual(league_ids, {1, 2})  # not 3 (unclaimed) or 4 (inactive)

        by_league = {entry["league_id"]: entry for entry in data}
        self.assertEqual(by_league[1]["league_name"], "Test League")
        self.assertEqual(by_league[1]["team_name"], "Team 1")
        self.assertEqual(by_league[1]["scoring_format"], "full_ppr")
        self.assertEqual(by_league[2]["league_name"], "Other League")
        self.assertEqual(by_league[2]["scoring_format"], "non_ppr")

        qb_slot = next(s for s in by_league[1]["slots"] if s["slot_name"] == "QB")
        self.assertEqual(qb_slot["player"]["player_id"], 1)  # Josh Allen

        other_qb_slot = next(s for s in by_league[2]["slots"] if s["slot_name"] == "QB")
        self.assertEqual(other_qb_slot["player"]["player_id"], 20)


if __name__ == "__main__":
    import unittest

    unittest.main()
