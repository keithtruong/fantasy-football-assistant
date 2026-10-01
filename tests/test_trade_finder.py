import unittest

from ffassistant.trade_finder import compute_trade_finder, starter_counts

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6}
POOL = {"QB": 20, "RB": 50, "WR": 60, "TE": 20}

_next_id = [0]


def player(position, pos_rank, status=None):
    _next_id[0] += 1
    return {
        "player_id": _next_id[0],
        "full_name": f"{position}{pos_rank}",
        "position": position,
        "rank": pos_rank,
        "pos_rank": pos_rank,
        "status": status,
    }


def team(team_id, players, is_mine=False):
    return {"team_id": team_id, "team_name": f"Team {team_id}", "is_mine": is_mine, "players": players}


def by_id(result, team_id):
    return next(t for t in result["teams"] if t["team_id"] == team_id)


class TestStarterCounts(unittest.TestCase):
    def test_flex_ignored_superflex_counts_toward_qb(self):
        counts = starter_counts({"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SUPER_FLEX": 1})
        self.assertEqual(counts, {"QB": 2, "RB": 2, "WR": 3, "TE": 1})


class TestComputeTradeFinder(unittest.TestCase):
    def test_splits_starters_depth_and_rest_best_first(self):
        rbs = [player("RB", r) for r in (30, 5, None, 12, 40)]
        result = compute_trade_finder(SLOTS, [team(1, rbs, is_mine=True)], POOL)
        rb = by_id(result, 1)["positions"]["RB"]
        self.assertEqual([p["pos_rank"] for p in rb["starters"]], [5, 12])
        self.assertEqual([p["pos_rank"] for p in rb["depth"]], [30, 40])
        # Unranked players sort last, never dropped.
        self.assertEqual([p["pos_rank"] for p in rb["rest"]], [None])

    def test_missing_and_unranked_players_score_as_double_pool_size(self):
        # One ranked RB starter, second starter slot empty.
        result = compute_trade_finder(SLOTS, [team(1, [player("RB", 10)], is_mine=True)], POOL)
        self.assertEqual(by_id(result, 1)["positions"]["RB"]["starter_avg"], (10 + 100) / 2)

    def test_one_good_depth_player_plus_filler_ranks_below_two_ranked(self):
        # The CSC case: WR28 + unranked must not out-rank WR51 + WR53 in
        # depth — a team won't trade its only usable backup.
        starters = [player("WR", 1), player("WR", 2)]
        teams = [
            team(1, starters + [player("WR", 51), player("WR", 53)], is_mine=True),
            team(2, [player("WR", 3), player("WR", 4), player("WR", 28), player("WR", None)]),
        ]
        result = compute_trade_finder(SLOTS, teams, POOL)
        self.assertEqual(by_id(result, 1)["positions"]["WR"]["depth_rank"], 1)
        self.assertEqual(by_id(result, 2)["positions"]["WR"]["depth_rank"], 2)

    def test_league_rank_lower_average_is_stronger(self):
        teams = [
            team(1, [player("WR", 1), player("WR", 2)], is_mine=True),
            team(2, [player("WR", 20), player("WR", 30)]),
        ]
        result = compute_trade_finder(SLOTS, teams, POOL)
        self.assertEqual(by_id(result, 1)["positions"]["WR"]["starter_rank"], 1)
        self.assertEqual(by_id(result, 2)["positions"]["WR"]["starter_rank"], 2)

    def test_fully_unranked_tier_gets_no_rank(self):
        # Most teams' backup QB is unranked — that shared tie must not read as
        # a mid-table (top-half) depth rank.
        teams = [team(i, [player("QB", i), player("QB", None)], is_mine=(i == 1)) for i in range(1, 5)]
        teams.append(team(5, [player("QB", 5), player("QB", 15)]))
        result = compute_trade_finder(SLOTS, teams, POOL)
        for team_id in range(1, 5):
            self.assertIsNone(by_id(result, team_id)["positions"]["QB"]["depth_rank"])
        self.assertEqual(by_id(result, 5)["positions"]["QB"]["depth_rank"], 1)

    def test_two_way_fit_when_needs_complement(self):
        # Mine: elite RBs with depth, weak WRs. Theirs: the mirror image.
        mine = [player("RB", r) for r in (1, 2, 3, 4)] + [player("WR", r) for r in (50, 55)]
        theirs = [player("RB", r) for r in (45, 48)] + [player("WR", r) for r in (1, 2, 3, 4)]
        middling = [player("RB", r) for r in (20, 21, 22, 23)] + [player("WR", r) for r in (20, 21, 22, 23)]
        teams = [team(1, mine, is_mine=True), team(2, theirs), team(3, middling), team(4, middling)]
        result = compute_trade_finder(SLOTS, teams, POOL)
        fits = by_id(result, 2)["fits"]
        self.assertEqual(fits["they_can_offer"], ["WR"])
        self.assertEqual(fits["they_need"], ["RB"])
        self.assertTrue(fits["two_way"])

    def test_my_team_has_no_fits(self):
        result = compute_trade_finder(SLOTS, [team(1, [], is_mine=True), team(2, [])], POOL)
        self.assertNotIn("fits", by_id(result, 1))
        self.assertIn("fits", by_id(result, 2))


if __name__ == "__main__":
    unittest.main()
