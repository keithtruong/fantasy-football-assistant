from tests.test_api import ApiTestCase


class ManualLeagueTestCase(ApiTestCase):
    def _create_manual_league(self, name="Manual League"):
        resp = self.client.post("/api/leagues", json={"name": name, "platform": "manual"})
        self.assertEqual(resp.status_code, 201)
        return resp.get_json()["league_id"]


class TestCreateManualLeague(ManualLeagueTestCase):
    def test_creates_without_platform_league_id(self):
        resp = self.client.post("/api/leagues", json={"name": "Yahoo Placeholder", "platform": "manual"})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertFalse(data["already_existed"])

        leagues = {l["league_id"]: l for l in self.client.get("/api/leagues").get_json()}
        league = leagues[data["league_id"]]
        self.assertEqual(league["platform"], "manual")
        self.assertIsNone(league["platform_league_id"])
        self.assertEqual(league["team_count"], 0)

    def test_requires_name(self):
        resp = self.client.post("/api/leagues", json={"platform": "manual"})
        self.assertEqual(resp.status_code, 400)

    def test_does_not_require_sync_and_never_calls_a_connector(self):
        # No mocked connector patched here at all — if create_league tried to
        # sync a manual league, this would blow up with an import/connection error.
        league_id = self._create_manual_league()
        self.assertIsInstance(league_id, int)

    def test_two_manual_leagues_dont_collide(self):
        # No platform_league_id to dedupe on, unlike real-platform leagues —
        # each POST must always create a new league.
        first = self._create_manual_league("League A")
        second = self._create_manual_league("League B")
        self.assertNotEqual(first, second)


class TestManualTeams(ManualLeagueTestCase):
    def test_add_team(self):
        league_id = self._create_manual_league()
        resp = self.client.post(f"/api/leagues/{league_id}/manual_teams", json={"team_name": "The Sharks"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["team_name"], "The Sharks")

        teams = self.client.get(f"/api/leagues/{league_id}/teams").get_json()
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]["team_name"], "The Sharks")

    def test_adding_team_updates_league_team_count(self):
        league_id = self._create_manual_league()
        self.client.post(f"/api/leagues/{league_id}/manual_teams", json={"team_name": "Team 1"})
        self.client.post(f"/api/leagues/{league_id}/manual_teams", json={"team_name": "Team 2"})

        leagues = {l["league_id"]: l for l in self.client.get("/api/leagues").get_json()}
        self.assertEqual(leagues[league_id]["team_count"], 2)

    def test_requires_team_name(self):
        league_id = self._create_manual_league()
        resp = self.client.post(f"/api/leagues/{league_id}/manual_teams", json={"team_name": "  "})
        self.assertEqual(resp.status_code, 400)

    def test_rejects_adding_team_to_a_platform_league(self):
        # league_id=1 from ApiTestCase's seed is platform='sleeper'.
        resp = self.client.post("/api/leagues/1/manual_teams", json={"team_name": "Nope"})
        self.assertEqual(resp.status_code, 400)

    def test_404_for_missing_league(self):
        resp = self.client.post("/api/leagues/999/manual_teams", json={"team_name": "X"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_team(self):
        league_id = self._create_manual_league()
        team_id = self.client.post(
            f"/api/leagues/{league_id}/manual_teams", json={"team_name": "The Sharks"}
        ).get_json()["team_id"]

        resp = self.client.delete(f"/api/leagues/{league_id}/manual_teams/{team_id}")
        self.assertEqual(resp.status_code, 204)

        teams = self.client.get(f"/api/leagues/{league_id}/teams").get_json()
        self.assertEqual(len(teams), 0)

        leagues = {l["league_id"]: l for l in self.client.get("/api/leagues").get_json()}
        self.assertEqual(leagues[league_id]["team_count"], 0)

    def test_delete_team_blocked_when_it_has_draft_picks(self):
        league_id = self._create_manual_league()
        team_id = self.client.post(
            f"/api/leagues/{league_id}/manual_teams", json={"team_name": "The Sharks"}
        ).get_json()["team_id"]
        self.client.put(f"/api/leagues/{league_id}/teams/{team_id}", json={"draft_position": 1})
        # player_id=2 comes from ApiTestCase's seed (Saquon Barkley).
        self.client.post(f"/api/leagues/{league_id}/draft_picks", json={"player_id": 2, "season": 2026})

        resp = self.client.delete(f"/api/leagues/{league_id}/manual_teams/{team_id}")
        self.assertEqual(resp.status_code, 409)

        teams = self.client.get(f"/api/leagues/{league_id}/teams").get_json()
        self.assertEqual(len(teams), 1)  # still there

    def test_delete_team_404_for_missing_team(self):
        league_id = self._create_manual_league()
        resp = self.client.delete(f"/api/leagues/{league_id}/manual_teams/999")
        self.assertEqual(resp.status_code, 404)

    def test_rejects_deleting_team_from_a_platform_league(self):
        resp = self.client.delete("/api/leagues/1/manual_teams/1")
        self.assertEqual(resp.status_code, 400)


class TestManualRosterSlots(ManualLeagueTestCase):
    def test_set_roster_slots(self):
        league_id = self._create_manual_league()
        resp = self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={
                "slots": [
                    {"slot_name": "QB", "slot_count": 1},
                    {"slot_name": "RB", "slot_count": 2},
                    {"slot_name": "BENCH", "slot_count": 6},
                ]
            },
        )
        self.assertEqual(resp.status_code, 200)

        settings = self.client.get(f"/api/leagues/{league_id}/settings").get_json()
        by_name = {s["slot_name"]: s["slot_count"] for s in settings["roster_slots"]}
        self.assertEqual(by_name, {"QB": 1, "RB": 2, "BENCH": 6})

    def test_set_roster_slots_is_a_full_replace(self):
        league_id = self._create_manual_league()
        self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "QB", "slot_count": 1}, {"slot_name": "RB", "slot_count": 2}]},
        )
        # Re-set with RB dropped entirely — old RB row must not survive.
        self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "QB", "slot_count": 1}]},
        )
        settings = self.client.get(f"/api/leagues/{league_id}/settings").get_json()
        self.assertEqual(settings["roster_slots"], [{"slot_name": "QB", "slot_count": 1}])

    def test_lowercases_are_normalized_to_uppercase(self):
        league_id = self._create_manual_league()
        self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "qb", "slot_count": 1}]},
        )
        settings = self.client.get(f"/api/leagues/{league_id}/settings").get_json()
        self.assertEqual(settings["roster_slots"], [{"slot_name": "QB", "slot_count": 1}])

    def test_zero_count_slots_are_dropped(self):
        league_id = self._create_manual_league()
        resp = self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "QB", "slot_count": 1}, {"slot_name": "K", "slot_count": 0}]},
        )
        self.assertEqual(resp.status_code, 200)
        settings = self.client.get(f"/api/leagues/{league_id}/settings").get_json()
        self.assertEqual(settings["roster_slots"], [{"slot_name": "QB", "slot_count": 1}])

    def test_rejects_negative_count(self):
        league_id = self._create_manual_league()
        resp = self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "QB", "slot_count": -1}]},
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_empty_slots_list(self):
        league_id = self._create_manual_league()
        resp = self.client.put(f"/api/leagues/{league_id}/roster_slots", json={"slots": []})
        self.assertEqual(resp.status_code, 400)

    def test_rejects_editing_a_platform_league(self):
        resp = self.client.put(
            "/api/leagues/1/roster_slots", json={"slots": [{"slot_name": "QB", "slot_count": 1}]}
        )
        self.assertEqual(resp.status_code, 400)


class TestManualLeagueDraftFlow(ManualLeagueTestCase):
    """End-to-end: a manual league can drive the same draft_picks/rankings
    machinery Draft/Grid/Tiers/Rosters already use for platform leagues."""

    def test_full_setup_and_a_recorded_pick(self):
        league_id = self._create_manual_league("Yahoo Draft Tomorrow")
        team_a = self.client.post(
            f"/api/leagues/{league_id}/manual_teams", json={"team_name": "Team A"}
        ).get_json()["team_id"]
        team_b = self.client.post(
            f"/api/leagues/{league_id}/manual_teams", json={"team_name": "Team B"}
        ).get_json()["team_id"]
        self.client.put(f"/api/leagues/{league_id}/teams/{team_a}", json={"draft_position": 1, "is_mine": True})
        self.client.put(f"/api/leagues/{league_id}/teams/{team_b}", json={"draft_position": 2})
        self.client.put(
            f"/api/leagues/{league_id}/roster_slots",
            json={"slots": [{"slot_name": "QB", "slot_count": 1}, {"slot_name": "RB", "slot_count": 2}]},
        )

        clock = self.client.get(f"/api/leagues/{league_id}/draft_picks?season=2026").get_json()["on_the_clock"]
        self.assertEqual(clock["team_id"], team_a)

        pick_resp = self.client.post(
            f"/api/leagues/{league_id}/draft_picks", json={"player_id": 2, "season": 2026}
        )
        self.assertEqual(pick_resp.status_code, 201)

        picks = self.client.get(f"/api/leagues/{league_id}/draft_picks?season=2026").get_json()["picks"]
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["team_id"], team_a)

        settings = self.client.get(f"/api/leagues/{league_id}/settings").get_json()
        total_rounds = sum(s["slot_count"] for s in settings["roster_slots"])
        self.assertEqual(total_rounds, 3)
