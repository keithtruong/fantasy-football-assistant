import unittest

from ffassistant.starters import compute_starters


def player(player_id, position, rank=None, flex_rank=None, op_rank=None, status="healthy", full_name=None):
    return {
        "player_id": player_id,
        "full_name": full_name or f"Player {player_id}",
        "position": position,
        "rank": rank,
        "flex_rank": flex_rank,
        "op_rank": op_rank,
        "status": status,
    }


class TestComputeStarters(unittest.TestCase):
    def test_fills_dedicated_slots_with_best_by_position_rank(self):
        roster_slots = {"QB": 1, "RB": 2, "WR": 1}
        players = [
            player(1, "QB", rank=5),
            player(2, "RB", rank=10),
            player(3, "RB", rank=3),
            player(4, "RB", rank=20),
            player(5, "WR", rank=1),
        ]
        result = compute_starters(roster_slots, players)

        starters_by_slot = [(s["slot_name"], s["player"]["player_id"] if s["player"] else None) for s in result["slots"]]
        self.assertEqual(starters_by_slot, [("QB", 1), ("RB", 3), ("RB", 2), ("WR", 5)])
        self.assertEqual([p["player_id"] for p in result["bench"]], [4])

    def test_flex_pulls_from_leftover_rb_wr_te_skipping_dedicated_picks(self):
        roster_slots = {"RB": 1, "WR": 1, "FLEX": 1}
        players = [
            player(1, "RB", rank=1, flex_rank=1),  # best RB overall, but only 1 RB slot
            player(2, "RB", rank=2, flex_rank=2),  # leftover RB, best remaining flex candidate
            player(3, "WR", rank=1, flex_rank=5),  # best WR, takes the WR slot
            player(4, "WR", rank=2, flex_rank=3),  # leftover WR, worse flex_rank than leftover RB
        ]
        result = compute_starters(roster_slots, players)

        flex_slot = [s for s in result["slots"] if s["slot_name"] == "FLEX"][0]
        self.assertEqual(flex_slot["player"]["player_id"], 2)  # leftover RB beats leftover WR by flex_rank
        self.assertEqual({p["player_id"] for p in result["bench"]}, {4})

    def test_superflex_pulls_from_leftover_including_qb_after_flex_assigned(self):
        roster_slots = {"QB": 1, "RB": 1, "FLEX": 1, "SUPER_FLEX": 1}
        players = [
            player(1, "QB", rank=1, op_rank=1),   # takes dedicated QB slot
            player(2, "QB", rank=2, op_rank=2),   # leftover QB, best remaining OP candidate
            player(3, "RB", rank=1, flex_rank=1, op_rank=5),  # takes dedicated RB slot
            player(4, "RB", rank=2, flex_rank=2, op_rank=6),  # takes FLEX (best remaining flex_rank)
            player(5, "WR", flex_rank=10, op_rank=10),  # worse than everyone for both flex/op
        ]
        result = compute_starters(roster_slots, players)

        by_slot = {s["slot_name"]: s["player"]["player_id"] if s["player"] else None for s in result["slots"]}
        self.assertEqual(by_slot["QB"], 1)
        self.assertEqual(by_slot["RB"], 3)
        self.assertEqual(by_slot["FLEX"], 4)
        self.assertEqual(by_slot["SUPER_FLEX"], 2)  # leftover QB beats leftover WR by op_rank
        self.assertEqual({p["player_id"] for p in result["bench"]}, {5})

    def test_unranked_players_sort_last_but_still_fill_a_slot_if_no_alternative(self):
        roster_slots = {"QB": 1}
        players = [player(1, "QB", rank=None)]
        result = compute_starters(roster_slots, players)

        self.assertEqual(result["slots"], [{"slot_name": "QB", "player": players[0]}])
        self.assertEqual(result["bench"], [])

    def test_ranked_player_preferred_over_unranked_for_same_slot(self):
        roster_slots = {"RB": 1}
        players = [player(1, "RB", rank=None), player(2, "RB", rank=7)]
        result = compute_starters(roster_slots, players)

        self.assertEqual(result["slots"][0]["player"]["player_id"], 2)
        self.assertEqual([p["player_id"] for p in result["bench"]], [1])

    def test_empty_slot_when_roster_lacks_the_position(self):
        roster_slots = {"QB": 1, "TE": 1}
        players = [player(1, "QB", rank=1)]
        result = compute_starters(roster_slots, players)

        by_slot = {s["slot_name"]: s["player"] for s in result["slots"]}
        self.assertIsNotNone(by_slot["QB"])
        self.assertIsNone(by_slot["TE"])
        self.assertEqual(result["bench"], [])

    def test_bench_and_ir_slots_are_ignored(self):
        roster_slots = {"QB": 1, "BENCH": 5, "IR": 1}
        players = [player(1, "QB", rank=1), player(2, "RB", rank=1)]
        result = compute_starters(roster_slots, players)

        self.assertEqual(len(result["slots"]), 1)
        self.assertEqual([p["player_id"] for p in result["bench"]], [2])


class TestBenchSortOrder(unittest.TestCase):
    def test_sorted_by_best_applicable_rank_across_position_flex_and_superflex(self):
        # No SUPER_FLEX slot in this league, so op_rank should NOT factor into
        # sort order even though every player has one.
        roster_slots = {"RB": 1, "FLEX": 1}
        players = [
            player(1, "RB", rank=1),                             # takes dedicated RB
            player(2, "RB", rank=5, flex_rank=3),                # takes FLEX
            player(3, "WR", rank=10, flex_rank=8, op_rank=99),   # bench: best applicable = 8 (flex)
            player(4, "TE", rank=2, flex_rank=20, op_rank=1),    # bench: best applicable = 2 (position; op_rank ignored, no SUPER_FLEX slot)
            player(5, "QB", rank=1, op_rank=1),                  # bench: best applicable = 1 (position only; op_rank ignored)
        ]
        result = compute_starters(roster_slots, players)

        self.assertEqual([p["player_id"] for p in result["bench"]], [5, 4, 3])

    def test_superflex_rank_counts_toward_sort_when_league_has_the_slot(self):
        roster_slots = {"QB": 1, "SUPER_FLEX": 1}
        players = [
            player(1, "QB", rank=1),                     # takes dedicated QB
            player(2, "RB", rank=50, op_rank=2),          # takes SUPER_FLEX via op_rank
            player(3, "WR", rank=40, op_rank=3),          # bench: best applicable = 3 (op_rank beats its own bad position rank)
            player(4, "TE", rank=5, op_rank=90),          # bench: best applicable = 5 (position beats its own bad op_rank)
        ]
        result = compute_starters(roster_slots, players)

        self.assertEqual([p["player_id"] for p in result["bench"]], [3, 4])

    def test_totally_unranked_players_sort_last_in_bench(self):
        roster_slots = {"QB": 1}
        players = [
            player(1, "QB", rank=1),
            player(2, "RB", rank=None),
            player(3, "WR", rank=7),
        ]
        result = compute_starters(roster_slots, players)

        self.assertEqual([p["player_id"] for p in result["bench"]], [3, 2])


if __name__ == "__main__":
    unittest.main()
