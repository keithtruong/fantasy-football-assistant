import sqlite3

from tests.test_api import ApiTestCase

SEASON = 2026
WEEK = 5


class TestStartersView(ApiTestCase):
    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._seed_starters(conn)
        conn.close()

    def _seed_starters(self, conn):
        # Base seed (ApiTestCase._seed) already gives league 1: roster_slots
        # QB=1/RB=2, team 1 "mine", players 1 (Josh Allen, QB), 2 (Saquon
        # Barkley, RB), 3 (Bijan Robinson, RB), and rec=1 -> full_ppr.
        conn.execute("INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (1, 'FLEX', 1)")
        conn.execute("INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (1, 'SUPER_FLEX', 1)")

        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (4, 'Some WR', 'WR', 'MIN')")
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (5, 'Backup QB', 'QB', 'LAC')")
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (6, 'Deep TE', 'TE', 'KC')")

        for player_id in (1, 2, 3, 4, 5, 6):
            conn.execute("INSERT INTO roster_spots (team_id, player_id) VALUES (1, ?)", (player_id,))

        # Standard per-position weekly ranks (list_type NULL).
        position_ranks = {1: 5, 2: 1, 3: 2, 4: 7, 5: 10, 6: 9}
        for player_id, rank in position_ranks.items():
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
                "VALUES (?, 'weekly', ?, ?, 'full_ppr', ?, NULL)",
                (player_id, SEASON, WEEK, rank),
            )

        # Combined FLEX (RB/WR/TE) ranks — Deep TE (6) beats Some WR (4).
        for player_id, rank in {4: 5, 6: 2}.items():
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
                "VALUES (?, 'weekly', ?, ?, 'full_ppr', ?, 'flex')",
                (player_id, SEASON, WEEK, rank),
            )

        # Combined SUPER_FLEX/OP (QB/RB/WR/TE) ranks — Backup QB (5) beats Some WR (4).
        for player_id, rank in {4: 10, 5: 1}.items():
            conn.execute(
                "INSERT INTO rankings (player_id, ranking_type, season, week, scoring_format, rank, list_type) "
                "VALUES (?, 'weekly', ?, ?, 'full_ppr', ?, 'superflex')",
                (player_id, SEASON, WEEK, rank),
            )
        conn.commit()

    def test_requires_week(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=starters&season={SEASON}")
        self.assertEqual(resp.status_code, 400)

    def test_fills_dedicated_flex_and_superflex_slots(self):
        resp = self.client.get(f"/api/leagues/1/in_season?view=starters&season={SEASON}&week={WEEK}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["scoring_format"], "full_ppr")

        by_slot = {}
        for slot in data["slots"]:
            by_slot.setdefault(slot["slot_name"], []).append(slot["player"]["player_id"] if slot["player"] else None)

        self.assertEqual(by_slot["QB"], [1])  # Josh Allen (rank 5) beats Backup QB (rank 10)
        self.assertEqual(sorted(by_slot["RB"]), [2, 3])
        self.assertEqual(by_slot["FLEX"], [6])  # Deep TE wins FLEX via combined rank (2 beats 5)
        self.assertEqual(by_slot["SUPER_FLEX"], [5])  # Backup QB wins leftover slot via combined rank (1 beats 10)

        bench_ids = {p["player_id"] for p in data["bench"]}
        self.assertEqual(bench_ids, {4})  # Some WR is the only player left over


if __name__ == "__main__":
    import unittest

    unittest.main()
