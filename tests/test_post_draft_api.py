from tests.test_api import ApiTestCase

SEASON = 2026


class PostDraftTestCase(ApiTestCase):
    """Reuses ApiTestCase's seeded league (4 teams) + players/rankings
    (Josh Allen rank 5, Saquon Barkley rank 1, Bijan Robinson rank 2, all
    'full_ppr')."""

    def _draft_all_four(self):
        # Snake draft, round 1: picks 1-4 go to teams 1-4 in draft_position order.
        for player_id in (2, 3, 1):
            self.client.post("/api/leagues/1/draft_picks", json={"player_id": player_id, "season": SEASON})


class TestGetPostDraftBeforeCompletion(PostDraftTestCase):
    def test_not_completed_when_never_marked(self):
        self._draft_all_four()
        resp = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}")
        data = resp.get_json()
        self.assertFalse(data["completed"])
        self.assertIsNone(data["completed_at"])
        self.assertEqual(len(data["picks"]), 3)
        self.assertTrue(all(p["snapshot_rank"] is None for p in data["picks"]))
        self.assertTrue(all(p["notable"] is False for p in data["picks"]))


class TestCompleteDraft(PostDraftTestCase):
    def test_requires_scoring_format(self):
        self._draft_all_four()
        resp = self.client.post("/api/leagues/1/post_draft/complete", json={"season": SEASON})
        self.assertEqual(resp.status_code, 400)

    def test_requires_existing_picks(self):
        resp = self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_404_for_missing_league(self):
        resp = self.client.post(
            "/api/leagues/99/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        self.assertEqual(resp.status_code, 404)

    def test_completes_and_snapshots_rankings(self):
        self._draft_all_four()
        resp = self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"completed": True, "scoring_format": "full_ppr"})

        status = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()
        self.assertTrue(status["completed"])
        self.assertEqual(status["scoring_format"], "full_ppr")
        self.assertIsNotNone(status["completed_at"])

    def test_pick_1_saquon_rank_1_is_not_notable(self):
        # Pick 1 = Saquon Barkley (rank 1) -> diff 1 - 1 = 0, not notable.
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        saquon = next(p for p in picks if p["full_name"] == "Saquon Barkley")
        self.assertEqual(saquon["snapshot_rank"], 1)
        self.assertEqual(saquon["rank_diff"], 0)
        self.assertFalse(saquon["notable"])

    def test_snapshot_pos_rank_computed_per_position(self):
        # RBs ordered by rank: Saquon (1) -> RB1, Bijan (2) -> RB2. Josh Allen
        # is the only QB in the snapshot -> QB1.
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        by_name = {p["full_name"]: p for p in picks}
        self.assertEqual(by_name["Saquon Barkley"]["snapshot_pos_rank"], 1)
        self.assertEqual(by_name["Bijan Robinson"]["snapshot_pos_rank"], 2)
        self.assertEqual(by_name["Josh Allen"]["snapshot_pos_rank"], 1)

    def test_josh_allen_rank_5_taken_pick_3_is_a_small_reach(self):
        # Pick 3 = Josh Allen (rank 5) -> taken 2 spots ahead of rank -> diff
        # 3 - 5 = -2 (negative = reach), below the notable threshold.
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        allen = next(p for p in picks if p["full_name"] == "Josh Allen")
        self.assertEqual(allen["rank_diff"], -2)
        self.assertFalse(allen["notable"])

    def test_reach_is_negative_and_notable_past_threshold(self):
        # Bijan Robinson (rank 2) taken at pick 2 in _draft_all_four, but if he'd
        # instead gone rank 2 and been taken pick 1, that's 1 spot ahead — not
        # enough to be notable. Push a clearer case: give a player a much worse
        # rank than where they were actually picked (a real reach).
        self._draft_all_four()
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE rankings SET rank = 20 WHERE player_id = 2 AND ranking_type = 'draft' AND scoring_format = 'full_ppr'"
        )
        conn.commit()
        conn.close()

        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        saquon = next(p for p in picks if p["full_name"] == "Saquon Barkley")
        # Taken pick 1 but ranked 20th -> diff = 1 - 20 = -19, a clear reach.
        self.assertEqual(saquon["rank_diff"], -19)
        self.assertTrue(saquon["notable"])

    def test_response_includes_team_id_for_grouping(self):
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        self.assertTrue(all("team_id" in p and p["team_id"] is not None for p in picks))

    def test_recompleting_replaces_prior_snapshot(self):
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )
        resp = self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "half_ppr"}
        )
        self.assertEqual(resp.status_code, 200)
        status = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()
        self.assertEqual(status["scoring_format"], "half_ppr")

    def test_snapshot_survives_future_rankings_resync(self):
        """The whole point of the snapshot: once frozen, a later rankings refresh
        (e.g. a full-replace resync moving Josh Allen from rank 5 to rank 1) must
        not change what this draft's post-draft view already reported."""
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )

        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE rankings SET rank = 1 WHERE player_id = 1 AND ranking_type = 'draft' AND scoring_format = 'full_ppr'"
        )
        conn.commit()
        conn.close()

        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        allen = next(p for p in picks if p["full_name"] == "Josh Allen")
        self.assertEqual(allen["snapshot_rank"], 5)


class TestReopenDraft(PostDraftTestCase):
    def test_reopen_clears_completion_and_snapshot(self):
        self._draft_all_four()
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )

        resp = self.client.delete(f"/api/leagues/1/post_draft/complete?season={SEASON}")
        self.assertEqual(resp.status_code, 204)

        status = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()
        self.assertFalse(status["completed"])
        self.assertTrue(all(p["snapshot_rank"] is None for p in status["picks"]))

    def test_reopen_keeps_picks_and_notes(self):
        self._draft_all_four()
        picks_before = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        pick_id = picks_before[0]["draft_pick_id"]
        self.client.put(f"/api/leagues/1/draft_picks/{pick_id}/notes", json={"notes": "keeper candidate"})
        self.client.post(
            "/api/leagues/1/post_draft/complete", json={"season": SEASON, "scoring_format": "full_ppr"}
        )

        self.client.delete(f"/api/leagues/1/post_draft/complete?season={SEASON}")

        picks_after = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        self.assertEqual(len(picks_after), 3)
        note = next(p["notes"] for p in picks_after if p["draft_pick_id"] == pick_id)
        self.assertEqual(note, "keeper candidate")


class TestPickNotes(PostDraftTestCase):
    def test_set_and_clear_notes(self):
        self._draft_all_four()
        pick = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"][0]

        resp = self.client.put(
            f"/api/leagues/1/draft_picks/{pick['draft_pick_id']}/notes", json={"notes": "watch the shoulder"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["notes"], "watch the shoulder")

        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        self.assertEqual(
            next(p["notes"] for p in picks if p["draft_pick_id"] == pick["draft_pick_id"]), "watch the shoulder"
        )

        self.client.put(f"/api/leagues/1/draft_picks/{pick['draft_pick_id']}/notes", json={"notes": ""})
        picks = self.client.get(f"/api/leagues/1/post_draft?season={SEASON}").get_json()["picks"]
        self.assertIsNone(next(p["notes"] for p in picks if p["draft_pick_id"] == pick["draft_pick_id"]))

    def test_404_for_missing_pick(self):
        resp = self.client.put("/api/leagues/1/draft_picks/999/notes", json={"notes": "x"})
        self.assertEqual(resp.status_code, 404)
