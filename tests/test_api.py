import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.api import create_app

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "test.db")

        seed_conn = _connect(self.db_path)
        seed_conn.executescript(SCHEMA_PATH.read_text())
        self._seed(seed_conn)
        seed_conn.close()

        self.patcher = patch("ffassistant.api.get_connection", side_effect=lambda: _connect(self.db_path))
        self.patcher.start()

        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.patcher.stop()
        self._tmpdir.cleanup()

    def _seed(self, conn):
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (1, 'Test League', 'sleeper', 4, 1)"
        )
        for i in range(1, 5):
            conn.execute(
                "INSERT INTO teams (team_id, league_id, team_name, is_mine, draft_position) VALUES (?, 1, ?, ?, ?)",
                (i, f"Team {i}", 1 if i == 1 else 0, i),
            )
        conn.execute("INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (1, 'QB', 1)")
        conn.execute("INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (1, 'RB', 2)")
        conn.execute("INSERT INTO league_scoring (league_id, stat_key, points) VALUES (1, 'rec', 1)")

        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (1, 'Josh Allen', 'QB', 'BUF')")
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (2, 'Saquon Barkley', 'RB', 'PHI')")
        conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (3, 'Bijan Robinson', 'RB', 'ATL')")

        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) VALUES (1, 'draft', 2026, 'full_ppr', 5)"
        )
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) VALUES (2, 'draft', 2026, 'full_ppr', 1)"
        )
        conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) VALUES (3, 'draft', 2026, 'full_ppr', 2)"
        )
        conn.execute("INSERT INTO nfl_team_byes (season, team, bye_week) VALUES (2026, 'BUF', 7)")
        conn.commit()


class TestLeaguesApi(ApiTestCase):
    def test_list_leagues(self):
        resp = self.client.get("/api/leagues")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["my_team_name"], "Team 1")

    def test_get_settings(self):
        resp = self.client.get("/api/leagues/1/settings")
        data = resp.get_json()
        self.assertEqual({r["slot_name"]: r["slot_count"] for r in data["roster_slots"]}, {"QB": 1, "RB": 2})
        self.assertEqual(data["scoring"], [{"stat_key": "rec", "points": 1}])

    def test_get_teams_empty_rosters(self):
        resp = self.client.get("/api/leagues/1/teams")
        data = resp.get_json()
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0]["roster"], [])

    def test_get_teams_includes_pick_number_for_draft_order(self):
        # Needed so the Rosters tab can derive starter-vs-bench from draft order.
        self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026})
        resp = self.client.get("/api/leagues/1/teams")
        team_one = next(t for t in resp.get_json() if t["team_id"] == 1)
        self.assertEqual(team_one["roster"][0]["pick_number"], 1)


class TestLeagueSettingsApi(ApiTestCase):
    def test_list_leagues_excludes_inactive_by_default(self):
        self.client.put("/api/leagues/1", json={"active": False})
        resp = self.client.get("/api/leagues")
        self.assertEqual(resp.get_json(), [])

    def test_list_leagues_include_inactive(self):
        self.client.put("/api/leagues/1", json={"active": False})
        resp = self.client.get("/api/leagues?include_inactive=1")
        self.assertEqual(len(resp.get_json()), 1)

    def test_update_league_name(self):
        resp = self.client.put("/api/leagues/1", json={"name": "Renamed League"})
        self.assertEqual(resp.status_code, 200)
        leagues = self.client.get("/api/leagues?include_inactive=1").get_json()
        self.assertEqual(leagues[0]["name"], "Renamed League")

    def test_delete_league_cascades_to_teams_and_picks(self):
        self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026})

        resp = self.client.delete("/api/leagues/1")
        self.assertEqual(resp.status_code, 204)

        leagues = self.client.get("/api/leagues?include_inactive=1").get_json()
        self.assertFalse(any(l["league_id"] == 1 for l in leagues))

        conn = _connect(self.db_path)
        self.assertEqual(conn.execute("SELECT COUNT(*) AS c FROM teams WHERE league_id = 1").fetchone()["c"], 0)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS c FROM draft_picks WHERE league_id = 1").fetchone()["c"], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) AS c FROM roster_slots WHERE league_id = 1").fetchone()["c"], 0
        )
        conn.close()

    def test_delete_league_404_for_missing_league(self):
        resp = self.client.delete("/api/leagues/999")
        self.assertEqual(resp.status_code, 404)

    def test_update_league_requires_a_field(self):
        resp = self.client.put("/api/leagues/1", json={})
        self.assertEqual(resp.status_code, 400)

    def test_update_league_404_for_missing_league(self):
        resp = self.client.put("/api/leagues/999", json={"name": "Nope"})
        self.assertEqual(resp.status_code, 404)

    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_create_league_syncs_and_sets_team_count(self, mock_sync):
        def fake_sync(conn, league_id, sleeper_league_id):
            conn.execute(
                "INSERT INTO teams (league_id, platform_team_id, team_name, draft_position) "
                "VALUES (?, '1', 'New Team', 1)",
                (league_id,),
            )
            conn.commit()

        mock_sync.side_effect = fake_sync

        resp = self.client.post(
            "/api/leagues",
            json={"name": "New League", "platform": "sleeper", "platform_league_id": "999", "season": 2026},
        )
        self.assertEqual(resp.status_code, 201)
        new_id = resp.get_json()["league_id"]

        leagues = {r["league_id"]: r for r in self.client.get("/api/leagues?include_inactive=1").get_json()}
        self.assertEqual(leagues[new_id]["team_count"], 1)  # derived from the synced team, not user-entered

    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_resubmitting_same_platform_league_id_resyncs_not_duplicates(self, mock_sync):
        # Real incident: a slow/ambiguous UI response led to 5 submits for one
        # real league, creating 5 duplicate rows. Re-adding the same
        # platform + platform_league_id must resync in place instead.
        def fake_sync(conn, league_id, sleeper_league_id):
            conn.execute("DELETE FROM teams WHERE league_id = ?", (league_id,))
            conn.execute(
                "INSERT INTO teams (league_id, platform_team_id, team_name, draft_position) "
                "VALUES (?, '1', 'Some Team', 1)",
                (league_id,),
            )
            conn.commit()

        mock_sync.side_effect = fake_sync

        first = self.client.post(
            "/api/leagues",
            json={"name": "Dup Test", "platform": "sleeper", "platform_league_id": "555", "season": 2026},
        )
        self.assertEqual(first.status_code, 201)
        first_id = first.get_json()["league_id"]

        second = self.client.post(
            "/api/leagues",
            json={"name": "Dup Test Renamed", "platform": "sleeper", "platform_league_id": "555", "season": 2026},
        )
        self.assertEqual(second.status_code, 200)  # not 201 — resynced, not created
        self.assertEqual(second.get_json()["league_id"], first_id)
        self.assertTrue(second.get_json()["already_existed"])

        leagues = self.client.get("/api/leagues?include_inactive=1").get_json()
        matching = [l for l in leagues if l["platform_league_id"] == "555"]
        self.assertEqual(len(matching), 1)  # only one row, not two
        self.assertEqual(matching[0]["name"], "Dup Test Renamed")

    def test_create_league_rejects_bad_platform(self):
        resp = self.client.post(
            "/api/leagues", json={"name": "X", "platform": "madeup", "platform_league_id": "1"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_error_responses_are_json_with_description(self):
        # abort() renders an HTML page by default — the frontend needs real JSON.
        resp = self.client.post(
            "/api/leagues", json={"name": "X", "platform": "madeup", "platform_league_id": "1"}
        )
        self.assertEqual(resp.content_type, "application/json")
        self.assertIn("platform", resp.get_json()["description"])

    def test_espn_non_numeric_league_id_gives_clear_error(self):
        # Real failure mode: someone types the league's display name instead of its
        # numeric ESPN ID into the platform_league_id field.
        resp = self.client.post(
            "/api/leagues",
            json={"name": "My League", "platform": "espn", "platform_league_id": "vegan"},
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("numeric", resp.get_json()["description"])

        leagues = self.client.get("/api/leagues?include_inactive=1").get_json()
        self.assertFalse(any(l["name"] == "My League" for l in leagues))

    @patch("ffassistant.ingest.sleeper.sync_league", side_effect=RuntimeError("boom"))
    def test_create_league_rolls_back_on_sync_failure(self, _mock_sync):
        resp = self.client.post(
            "/api/leagues",
            json={"name": "Broken League", "platform": "sleeper", "platform_league_id": "999"},
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("boom", resp.get_json()["description"])

        leagues = self.client.get("/api/leagues?include_inactive=1").get_json()
        self.assertFalse(any(l["name"] == "Broken League" for l in leagues))

    @patch("ffassistant.ingest.sleeper.sync_league")
    def test_resync_existing_league(self, mock_sync):
        resp = self.client.post("/api/leagues/1/sync", json={"season": 2026})
        self.assertEqual(resp.status_code, 200)
        mock_sync.assert_called_once()

    def test_resync_404_for_missing_league(self):
        resp = self.client.post("/api/leagues/999/sync", json={})
        self.assertEqual(resp.status_code, 404)

    def test_update_team_draft_position(self):
        resp = self.client.put("/api/leagues/1/teams/1", json={"draft_position": 4})
        self.assertEqual(resp.status_code, 200)
        teams = self.client.get("/api/leagues/1/teams").get_json()
        team_one = next(t for t in teams if t["team_id"] == 1)
        self.assertEqual(team_one["draft_position"], 4)

    def test_setting_is_mine_clears_previous_teams_flag(self):
        self.client.put("/api/leagues/1/teams/2", json={"is_mine": True})
        teams = self.client.get("/api/leagues/1/teams").get_json()
        mine = [t for t in teams if t["is_mine"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["team_id"], 2)


class TestRankingsApi(ApiTestCase):
    def test_returns_ordered_by_rank_with_bye_week_joined(self):
        resp = self.client.get("/api/leagues/1/rankings?scoring_format=full_ppr&season=2026")
        data = resp.get_json()
        self.assertEqual([r["full_name"] for r in data], ["Saquon Barkley", "Bijan Robinson", "Josh Allen"])
        allen = next(r for r in data if r["full_name"] == "Josh Allen")
        self.assertEqual(allen["bye_week"], 7)

    def test_includes_already_drafted_players(self):
        # Rankings always returns the full pool — the client filters "available"
        # using the draft-picks list it already has, not a second server-side view.
        self.client.post(
            "/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026}
        )
        resp = self.client.get("/api/leagues/1/rankings?scoring_format=full_ppr&season=2026")
        names = [r["full_name"] for r in resp.get_json()]
        self.assertIn("Saquon Barkley", names)


class TestDraftPicksApi(ApiTestCase):
    def test_pick_order_and_on_the_clock(self):
        resp = self.client.get("/api/leagues/1/draft_picks?season=2026")
        data = resp.get_json()
        self.assertEqual(data["picks"], [])
        self.assertEqual(data["on_the_clock"]["pick_number"], 1)
        self.assertEqual(data["on_the_clock"]["team_name"], "Team 1")

    def test_record_pick_advances_clock_in_snake_order(self):
        r1 = self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.get_json()["team_id"], 1)

        clock = self.client.get("/api/leagues/1/draft_picks?season=2026").get_json()["on_the_clock"]
        self.assertEqual(clock["pick_number"], 2)
        self.assertEqual(clock["team_name"], "Team 2")

    def test_edit_pick_swaps_player(self):
        pick = self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026}).get_json()
        resp = self.client.put(f"/api/leagues/1/draft_picks/{pick['draft_pick_id']}", json={"player_id": 3})
        self.assertEqual(resp.status_code, 200)

        picks = self.client.get("/api/leagues/1/draft_picks?season=2026").get_json()["picks"]
        self.assertEqual(picks[0]["full_name"], "Bijan Robinson")

    def test_undo_most_recent_pick(self):
        pick = self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026}).get_json()
        resp = self.client.delete(f"/api/leagues/1/draft_picks/{pick['draft_pick_id']}")
        self.assertEqual(resp.status_code, 204)

        clock = self.client.get("/api/leagues/1/draft_picks?season=2026").get_json()["on_the_clock"]
        self.assertEqual(clock["pick_number"], 1)  # back to square one

    def test_cannot_undo_a_non_recent_pick(self):
        first = self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026}).get_json()
        self.client.post("/api/leagues/1/draft_picks", json={"player_id": 3, "season": 2026})

        resp = self.client.delete(f"/api/leagues/1/draft_picks/{first['draft_pick_id']}")
        self.assertEqual(resp.status_code, 409)


class TestPlayersApi(ApiTestCase):
    def test_search_requires_min_length(self):
        resp = self.client.get("/api/players/search?q=J")
        self.assertEqual(resp.get_json(), [])

    def test_search_matches_substring(self):
        resp = self.client.get("/api/players/search?q=allen")
        data = resp.get_json()
        self.assertEqual([r["full_name"] for r in data], ["Josh Allen"])

    def test_search_excludes_drafted_players_for_league(self):
        self.client.post("/api/leagues/1/draft_picks", json={"player_id": 2, "season": 2026})
        resp = self.client.get("/api/players/search?q=barkley&league_id=1&season=2026")
        self.assertEqual(resp.get_json(), [])


if __name__ == "__main__":
    unittest.main()
