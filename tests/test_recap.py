import unittest

from ffassistant.recap import (
    apply_narratives,
    best_team_by_slot,
    biggest_win_and_closest_matchup,
    high_low_scores,
    matchup_details,
    matchup_results,
    narrative_brief,
    narrative_key,
    next_week_preview,
    optimal_lineup_pct,
    performance_vs_projection,
    score_by_checkpoint,
    start_sit_gaffes,
    team_projected_score,
    team_standings,
    team_weekly_scores,
    time_window_for,
    top_performers_by_position,
    top_players_for_team,
    upcoming_matchup_pairs,
    waiver_wire_difference_makers,
)


def row(team_id, player_id, position, slot_name, points, full_name=None, game_date=None, projected_points=None):
    return {
        "team_id": team_id,
        "player_id": player_id,
        "full_name": full_name or f"Player {player_id}",
        "position": position,
        "slot_name": slot_name,
        "points": points,
        "game_date": game_date,
        "projected_points": projected_points,
    }


TEAM_NAMES = {1: "Team One", 2: "Team Two", 3: "Team Three"}


class TestTeamWeeklyScores(unittest.TestCase):
    def test_sums_started_points_excludes_bench_and_ir(self):
        box_scores = [
            row(1, 101, "QB", "QB", 20.0),
            row(1, 102, "RB", "BENCH", 15.0),
            row(1, 103, "WR", "IR", 0.0),
            row(2, 201, "QB", "QB", 10.0),
            row(2, 202, "RB", "RB", 5.0),
        ]
        self.assertEqual(team_weekly_scores(box_scores), {1: 20.0, 2: 15.0})


class TestHighLowScores(unittest.TestCase):
    def test_picks_highest_and_lowest(self):
        result = high_low_scores({1: 100.0, 2: 60.0, 3: 145.5}, TEAM_NAMES)
        self.assertEqual(result["highest"], {"team_id": 3, "team_name": "Team Three", "points": 145.5})
        self.assertEqual(result["lowest"], {"team_id": 2, "team_name": "Team Two", "points": 60.0})

    def test_empty_scores_returns_none_both(self):
        self.assertEqual(high_low_scores({}, TEAM_NAMES), {"highest": None, "lowest": None})


class TestMatchupsAndBiggestClosest(unittest.TestCase):
    def test_collapses_both_directions_into_one_entry_each(self):
        team_scores = {1: 120.0, 2: 100.0, 3: 90.0, 4: 88.0}
        pairs = [(1, 2), (2, 1), (3, 4), (4, 3)]
        matchups = matchup_results(team_scores, TEAM_NAMES, pairs)
        self.assertEqual(len(matchups), 2)

        margins = sorted(m["margin"] for m in matchups)
        self.assertEqual(margins, [2.0, 20.0])

    def test_skips_matchup_missing_a_scored_side(self):
        team_scores = {1: 120.0}  # team 2 not scored yet
        matchups = matchup_results(team_scores, TEAM_NAMES, [(1, 2), (2, 1)])
        self.assertEqual(matchups, [])

    def test_biggest_win_and_closest_matchup(self):
        team_scores = {1: 120.0, 2: 100.0, 3: 90.0, 4: 88.0}
        matchups = matchup_results(team_scores, TEAM_NAMES, [(1, 2), (2, 1), (3, 4), (4, 3)])
        result = biggest_win_and_closest_matchup(matchups)
        self.assertEqual(result["biggest_win"]["margin"], 20.0)
        self.assertEqual(result["closest_matchup"]["margin"], 2.0)

    def test_no_matchups_returns_none_both(self):
        self.assertEqual(biggest_win_and_closest_matchup([]), {"biggest_win": None, "closest_matchup": None})


class TestTopPerformersByPosition(unittest.TestCase):
    def test_sorts_best_first_across_started_and_benched(self):
        box_scores = [
            row(1, 101, "RB", "RB", 30.0, full_name="Starter RB"),
            row(2, 102, "RB", "BENCH", 40.0, full_name="Bench Monster"),
            row(1, 103, "QB", "QB", 25.0),
        ]
        result = top_performers_by_position(box_scores, limit=2)
        self.assertEqual([p["full_name"] for p in result["RB"]], ["Bench Monster", "Starter RB"])
        self.assertEqual(len(result["QB"]), 1)

    def test_limit_is_respected(self):
        box_scores = [row(1, i, "WR", "WR", float(i)) for i in range(5)]
        result = top_performers_by_position(box_scores, limit=3)
        self.assertEqual(len(result["WR"]), 3)
        self.assertEqual([p["player_id"] for p in result["WR"]], [4, 3, 2])


class TestBestTeamBySlot(unittest.TestCase):
    def test_flexed_player_credited_to_real_position_not_flex(self):
        box_scores = [
            row(1, 101, "RB", "RB", 10.0, full_name="Dedicated RB"),
            row(1, 102, "RB", "FLEX", 25.0, full_name="Flexed RB"),  # flexed RB — should count toward team 1's RB total
            row(2, 201, "RB", "RB", 20.0),
        ]
        result = best_team_by_slot(box_scores, TEAM_NAMES)
        self.assertEqual(result["RB"]["team_id"], 1)  # 10 + 25 = 35 beats team 2's 20
        self.assertEqual(result["RB"]["points"], 35.0)
        self.assertEqual([p["full_name"] for p in result["RB"]["players"]], ["Flexed RB", "Dedicated RB"])

    def test_bench_bucket_excludes_ir(self):
        box_scores = [
            row(1, 101, "RB", "BENCH", 12.0, full_name="Bench Guy"),
            row(1, 102, "WR", "IR", 99.0),  # IR — must not count as bench
            row(2, 201, "TE", "BENCH", 5.0),
        ]
        result = best_team_by_slot(box_scores, TEAM_NAMES)
        self.assertEqual(
            result["BENCH"],
            {
                "team_id": 1,
                "team_name": "Team One",
                "points": 12.0,
                "players": [{"player_id": 101, "full_name": "Bench Guy", "points": 12.0}],
            },
        )

    def test_position_with_no_data_is_none(self):
        box_scores = [row(1, 101, "QB", "QB", 10.0)]
        result = best_team_by_slot(box_scores, TEAM_NAMES)
        self.assertIsNone(result["K"])
        self.assertIsNone(result["BENCH"])


class TestOptimalLineupPct(unittest.TestCase):
    def test_perfect_lineup_is_100_percent(self):
        roster_slots = {"QB": 1, "RB": 1}
        team_box_scores = [
            row(1, 101, "QB", "QB", 20.0),
            row(1, 102, "RB", "RB", 15.0),
        ]
        result = optimal_lineup_pct(roster_slots, team_box_scores)
        self.assertEqual(result["actual_points"], 35.0)
        self.assertEqual(result["optimal_points"], 35.0)
        self.assertAlmostEqual(result["pct"], 100.0)

    def test_started_worse_player_than_bench_lowers_pct(self):
        roster_slots = {"RB": 1, "BENCH": 1}
        team_box_scores = [
            row(1, 101, "RB", "RB", 5.0),  # started, but worse
            row(1, 102, "RB", "BENCH", 25.0),  # benched, but better — should have started
        ]
        result = optimal_lineup_pct(roster_slots, team_box_scores)
        self.assertEqual(result["actual_points"], 5.0)
        self.assertEqual(result["optimal_points"], 25.0)
        self.assertAlmostEqual(result["pct"], 20.0)

    def test_flex_considered_in_optimal(self):
        roster_slots = {"RB": 1, "WR": 1, "FLEX": 1}
        team_box_scores = [
            row(1, 101, "RB", "RB", 10.0),
            row(1, 102, "WR", "WR", 8.0),
            row(1, 103, "RB", "BENCH", 30.0),  # should be the optimal FLEX pick
            row(1, 104, "TE", "BENCH", 2.0),
        ]
        result = optimal_lineup_pct(roster_slots, team_box_scores)
        self.assertEqual(result["optimal_points"], 10.0 + 8.0 + 30.0)

    def test_empty_roster_pct_is_none(self):
        result = optimal_lineup_pct({"QB": 1}, [])
        self.assertIsNone(result["pct"])
        self.assertEqual(result["optimal_points"], 0)


class TestStartSitGaffes(unittest.TestCase):
    def test_flags_starter_outscored_by_eligible_bench_player(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 4.0, full_name="Bust"),
            row(1, 102, "RB", "BENCH", 22.0, full_name="Should've Started"),
        ]
        gaffes = start_sit_gaffes(team_box_scores)
        self.assertEqual(len(gaffes), 1)
        gaffe = gaffes[0]
        self.assertEqual(gaffe["started"]["full_name"], "Bust")
        self.assertEqual(gaffe["benched"]["full_name"], "Should've Started")
        self.assertEqual(gaffe["missed_points"], 18.0)

    def test_no_gaffe_when_starter_already_best(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 30.0),
            row(1, 102, "RB", "BENCH", 5.0),
        ]
        self.assertEqual(start_sit_gaffes(team_box_scores), [])

    def test_bench_player_must_be_position_eligible_for_dedicated_slot(self):
        team_box_scores = [
            row(1, 101, "QB", "QB", 5.0),
            row(1, 102, "WR", "BENCH", 40.0),  # huge bench day, but not QB-eligible
        ]
        self.assertEqual(start_sit_gaffes(team_box_scores), [])

    def test_flex_slot_checks_flex_eligible_bench_players(self):
        team_box_scores = [
            row(1, 101, "WR", "FLEX", 3.0, full_name="Flex Bust"),
            row(1, 102, "RB", "BENCH", 19.0, full_name="Flex Sleeper"),
            row(1, 103, "QB", "BENCH", 99.0),  # not flex-eligible, must not be picked
        ]
        gaffes = start_sit_gaffes(team_box_scores)
        self.assertEqual(len(gaffes), 1)
        self.assertEqual(gaffes[0]["benched"]["full_name"], "Flex Sleeper")

    def test_worst_gaffe_sorted_first(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 10.0, full_name="Small Miss"),
            row(1, 102, "RB", "BENCH", 15.0, full_name="Small Alt"),
            row(1, 103, "WR", "WR", 2.0, full_name="Big Miss"),
            row(1, 104, "WR", "BENCH", 40.0, full_name="Big Alt"),
        ]
        gaffes = start_sit_gaffes(team_box_scores)
        self.assertEqual([g["started"]["full_name"] for g in gaffes], ["Big Miss", "Small Miss"])


class TestWaiverWireDifferenceMakers(unittest.TestCase):
    def fa(self, player_id, full_name, position, points):
        return {"player_id": player_id, "full_name": full_name, "position": position, "points": points}

    def test_top_scorers_sorted_and_limited(self):
        free_agents = [self.fa(1, "Low", "RB", 5.0), self.fa(2, "High", "RB", 30.0), self.fa(3, "Mid", "WR", 15.0)]
        result = waiver_wire_difference_makers(free_agents, box_scores=[], limit=2)
        self.assertEqual([r["full_name"] for r in result], ["High", "Mid"])

    def test_flags_beating_the_lowest_started_score_at_that_position(self):
        free_agents = [self.fa(1, "Waiver Steal", "RB", 20.0)]
        box_scores = [
            row(1, 101, "RB", "RB", 25.0),  # started RB, higher than the free agent
            row(1, 102, "RB", "RB", 8.0),  # started RB, lower than the free agent — the floor
        ]
        result = waiver_wire_difference_makers(free_agents, box_scores)
        self.assertTrue(result[0]["beat_lowest_starter_at_position"])
        self.assertEqual(result[0]["lowest_starter_points"], 8.0)

    def test_does_not_flag_when_free_agent_fails_to_beat_the_floor(self):
        free_agents = [self.fa(1, "Not That Special", "RB", 5.0)]
        box_scores = [row(1, 101, "RB", "RB", 8.0)]
        result = waiver_wire_difference_makers(free_agents, box_scores)
        self.assertFalse(result[0]["beat_lowest_starter_at_position"])

    def test_bench_and_ir_excluded_from_the_floor_calculation(self):
        free_agents = [self.fa(1, "Free Agent", "RB", 10.0)]
        box_scores = [
            row(1, 101, "RB", "BENCH", 1.0),  # benched — must not set an artificially low floor
            row(1, 102, "RB", "IR", 0.5),
        ]
        result = waiver_wire_difference_makers(free_agents, box_scores)
        self.assertIsNone(result[0]["lowest_starter_points"])  # nobody actually started an RB

    def test_no_starters_at_position_gives_none_floor(self):
        free_agents = [self.fa(1, "Lone Kicker", "K", 9.0)]
        result = waiver_wire_difference_makers(free_agents, box_scores=[])
        self.assertIsNone(result[0]["lowest_starter_points"])
        self.assertFalse(result[0]["beat_lowest_starter_at_position"])


class TestTimeWindowFor(unittest.TestCase):
    def test_thursday_is_thursday_night(self):
        self.assertEqual(time_window_for("2025-09-04T19:15:00"), "Thursday Night")

    def test_monday_is_monday_night(self):
        self.assertEqual(time_window_for("2025-09-08T19:15:00"), "Monday Night")

    def test_sunday_before_2pm_is_morning(self):
        self.assertEqual(time_window_for("2025-09-07T12:00:00"), "Sunday Morning")

    def test_sunday_between_2_and_6_is_afternoon(self):
        self.assertEqual(time_window_for("2025-09-07T15:05:00"), "Sunday Afternoon")

    def test_sunday_after_6pm_is_night(self):
        self.assertEqual(time_window_for("2025-09-07T19:20:00"), "Sunday Night")

    def test_none_is_other(self):
        self.assertEqual(time_window_for(None), "Other")

    def test_saturday_is_other(self):
        self.assertEqual(time_window_for("2025-08-30T16:00:00"), "Other")


class TestScoreByCheckpoint(unittest.TestCase):
    def test_builds_chronological_cumulative_series(self):
        team_box_scores = [
            row(1, 101, "QB", "QB", 20.0, full_name="Thu QB", game_date="2025-09-04T19:15:00"),
            row(1, 102, "RB", "RB", 10.0, full_name="Sun Early RB", game_date="2025-09-07T12:00:00"),
            row(1, 103, "WR", "WR", 15.0, full_name="Sun Night WR", game_date="2025-09-07T19:20:00"),
        ]
        series = score_by_checkpoint(team_box_scores)
        self.assertEqual([s["window"] for s in series], ["Thursday Night", "Sunday Morning", "Sunday Night"])
        self.assertEqual([s["cumulative_points"] for s in series], [20.0, 30.0, 45.0])
        self.assertEqual(series[0]["players"][0]["full_name"], "Thu QB")

    def test_omits_windows_with_no_games(self):
        team_box_scores = [row(1, 101, "QB", "QB", 20.0, game_date="2025-09-04T19:15:00")]
        series = score_by_checkpoint(team_box_scores)
        self.assertEqual(len(series), 1)

    def test_bench_and_ir_excluded(self):
        team_box_scores = [
            row(1, 101, "QB", "QB", 20.0, game_date="2025-09-04T19:15:00"),
            row(1, 102, "RB", "BENCH", 99.0, game_date="2025-09-07T12:00:00"),
        ]
        series = score_by_checkpoint(team_box_scores)
        self.assertEqual(len(series), 1)  # bench player's window never appears
        self.assertEqual(series[0]["cumulative_points"], 20.0)

    def test_multiple_players_same_window_sorted_best_first(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 5.0, full_name="Small Game", game_date="2025-09-07T12:00:00"),
            row(1, 102, "WR", "WR", 25.0, full_name="Big Game", game_date="2025-09-07T12:30:00"),
        ]
        series = score_by_checkpoint(team_box_scores)
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["points_this_window"], 30.0)
        self.assertEqual([p["full_name"] for p in series[0]["players"]], ["Big Game", "Small Game"])


class TestTopPlayersForTeam(unittest.TestCase):
    def test_sorts_best_first_and_respects_limit(self):
        team_box_scores = [
            row(1, 101, "QB", "QB", 20.0, full_name="QB"),
            row(1, 102, "RB", "RB", 30.0, full_name="RB"),
            row(1, 103, "WR", "WR", 10.0, full_name="WR"),
        ]
        result = top_players_for_team(team_box_scores, limit=2)
        self.assertEqual([p["full_name"] for p in result], ["RB", "QB"])

    def test_bench_excluded(self):
        team_box_scores = [row(1, 101, "RB", "BENCH", 99.0)]
        self.assertEqual(top_players_for_team(team_box_scores), [])


class TestPerformanceVsProjection(unittest.TestCase):
    def test_flags_overperformance_and_underperformance(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 30.0, full_name="Boom", projected_points=12.0),
            row(1, 102, "WR", "WR", 2.0, full_name="Bust", projected_points=15.0),
        ]
        result = performance_vs_projection(team_box_scores)
        tags = {p["full_name"]: p["tag"] for p in result}
        self.assertEqual(tags, {"Boom": "over", "Bust": "under"})

    def test_small_deltas_filtered_by_threshold(self):
        team_box_scores = [row(1, 101, "RB", "RB", 11.0, projected_points=12.0)]
        self.assertEqual(performance_vs_projection(team_box_scores), [])

    def test_missing_projection_is_skipped_not_treated_as_zero(self):
        team_box_scores = [row(1, 101, "RB", "RB", 20.0, projected_points=None)]
        self.assertEqual(performance_vs_projection(team_box_scores), [])

    def test_sorted_by_biggest_surprise_first(self):
        team_box_scores = [
            row(1, 101, "RB", "RB", 20.0, full_name="Small Surprise", projected_points=12.0),
            row(1, 102, "WR", "WR", 40.0, full_name="Big Surprise", projected_points=10.0),
        ]
        result = performance_vs_projection(team_box_scores)
        self.assertEqual([p["full_name"] for p in result], ["Big Surprise", "Small Surprise"])

    def test_bench_excluded(self):
        team_box_scores = [row(1, 101, "RB", "BENCH", 99.0, projected_points=1.0)]
        self.assertEqual(performance_vs_projection(team_box_scores), [])


class TestMatchupDetails(unittest.TestCase):
    def test_closest_matchup_is_first_and_flagged(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "points": 120.0},
                "team_b": {"team_id": 2, "team_name": "B", "points": 90.0},
                "margin": 30.0,
            },
            {
                "team_a": {"team_id": 3, "team_name": "C", "points": 100.0},
                "team_b": {"team_id": 4, "team_name": "D", "points": 99.5},
                "margin": 0.5,
            },
        ]
        box_scores_by_team = {
            1: [row(1, 1, "QB", "QB", 20.0)],
            2: [row(2, 2, "QB", "QB", 15.0)],
            3: [row(3, 3, "QB", "QB", 25.0)],
            4: [row(4, 4, "QB", "QB", 22.0)],
        }
        result = matchup_details(matchups, box_scores_by_team)
        self.assertEqual([m["margin"] for m in result], [0.5, 30.0])
        self.assertTrue(result[0]["is_matchup_of_the_week"])
        self.assertFalse(result[1]["is_matchup_of_the_week"])

    def test_each_side_gets_full_detail(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "points": 20.0},
                "team_b": {"team_id": 2, "team_name": "B", "points": 15.0},
                "margin": 5.0,
            }
        ]
        box_scores_by_team = {
            1: [row(1, 1, "QB", "QB", 20.0, full_name="A's QB", game_date="2025-09-07T13:00:00", projected_points=8.0)],
            2: [row(2, 2, "QB", "QB", 15.0, full_name="B's QB")],
        }
        result = matchup_details(matchups, box_scores_by_team)
        detail_a = result[0]["team_a_detail"]
        self.assertEqual(len(detail_a["score_by_checkpoint"]), 1)
        self.assertEqual(detail_a["top_players"][0]["full_name"], "A's QB")
        self.assertEqual(detail_a["performance_vs_projection"][0]["tag"], "over")

    def test_missing_team_in_box_scores_gets_empty_detail_not_a_crash(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "points": 20.0},
                "team_b": {"team_id": 2, "team_name": "B", "points": 15.0},
                "margin": 5.0,
            }
        ]
        result = matchup_details(matchups, box_scores_by_team={})
        self.assertEqual(result[0]["team_a_detail"]["top_players"], [])
        self.assertEqual(result[0]["team_b_detail"]["score_by_checkpoint"], [])

    def test_empty_matchups_returns_empty_list(self):
        self.assertEqual(matchup_details([], {}), [])


class TestNarrativeKey(unittest.TestCase):
    def test_same_key_regardless_of_side_order(self):
        self.assertEqual(narrative_key(3, 7), narrative_key(7, 3))

    def test_key_format(self):
        self.assertEqual(narrative_key(7, 3), "3-7")


class TestNarrativeBrief(unittest.TestCase):
    def _sample_details(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "points": 120.0},
                "team_b": {"team_id": 2, "team_name": "B", "points": 90.0},
                "margin": 30.0,
            }
        ]
        box_scores_by_team = {
            1: [row(1, 1, "QB", "QB", 20.0, full_name="A's QB", game_date="2025-09-07T13:00:00", projected_points=8.0)],
            2: [row(2, 2, "QB", "QB", 15.0, full_name="B's QB")],
        }
        return matchup_details(matchups, box_scores_by_team)

    def test_brief_is_flat_and_keyed(self):
        details = self._sample_details()
        brief = narrative_brief(details)
        self.assertEqual(len(brief), 1)
        entry = brief[0]
        self.assertEqual(entry["key"], "1-2")
        self.assertEqual(entry["team_a"], "A")
        self.assertEqual(entry["team_b"], "B")
        self.assertEqual(entry["score_a"], 120.0)
        self.assertEqual(entry["score_b"], 90.0)
        self.assertEqual(entry["margin"], 30.0)
        self.assertTrue(entry["is_matchup_of_the_week"])
        self.assertEqual(entry["top_players_a"][0]["full_name"], "A's QB")
        self.assertEqual(entry["surprises_a"][0]["tag"], "over")
        self.assertEqual(entry["surprises_b"], [])

    def test_brief_round_trips_into_apply_narratives(self):
        details = self._sample_details()
        brief = narrative_brief(details)
        narratives = {entry["key"]: f"Narrative for {entry['team_a']} vs {entry['team_b']}" for entry in brief}
        merged = apply_narratives(details, narratives)
        self.assertEqual(merged[0]["narrative"], "Narrative for A vs B")


class TestApplyNarratives(unittest.TestCase):
    def _sample_details(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "points": 20.0},
                "team_b": {"team_id": 2, "team_name": "B", "points": 15.0},
                "margin": 5.0,
            },
            {
                "team_a": {"team_id": 3, "team_name": "C", "points": 40.0},
                "team_b": {"team_id": 4, "team_name": "D", "points": 10.0},
                "margin": 30.0,
            },
        ]
        return matchup_details(matchups, box_scores_by_team={})

    def test_matching_key_gets_narrative(self):
        details = self._sample_details()
        merged = apply_narratives(details, {"1-2": "They fought hard."})
        by_key = {narrative_key(m["team_a"]["team_id"], m["team_b"]["team_id"]): m for m in merged}
        self.assertEqual(by_key["1-2"]["narrative"], "They fought hard.")

    def test_missing_key_keeps_existing_narrative_instead_of_erroring(self):
        details = self._sample_details()
        details[1]["narrative"] = "Already had one."
        merged = apply_narratives(details, {"1-2": "They fought hard."})
        by_key = {narrative_key(m["team_a"]["team_id"], m["team_b"]["team_id"]): m for m in merged}
        self.assertEqual(by_key["3-4"]["narrative"], "Already had one.")

    def test_empty_narratives_dict_leaves_everything_none(self):
        details = self._sample_details()
        merged = apply_narratives(details, {})
        self.assertTrue(all(m.get("narrative") is None for m in merged))


def team_row(team_id, standing, playoff_pct=None, wins=0, losses=0, ties=0, points_for=None, team_name=None):
    return {
        "team_id": team_id,
        "team_name": team_name or f"Team {team_id}",
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "points_for": points_for,
        "points_against": None,
        "playoff_pct": playoff_pct,
        "standing": standing,
    }


def standing_row(team_id, rank, playoff_pct=None, wins=0, losses=0, ties=0, points_for=None, team_name=None):
    """A team_standings()-shaped row (already carrying 'rank') — for testing
    next_week_preview directly, without going through team_standings' own
    standing-to-rank derivation (that has its own TestTeamStandings above)."""
    return {
        "team_id": team_id,
        "team_name": team_name or f"Team {team_id}",
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "points_for": points_for,
        "points_against": None,
        "playoff_pct": playoff_pct,
        "standing": rank,
        "rank": rank,
    }


class TestTeamStandings(unittest.TestCase):
    def test_ranks_by_espn_standing(self):
        teams = [team_row(1, standing=3), team_row(2, standing=1), team_row(3, standing=2)]
        result = team_standings(teams)
        self.assertEqual([t["team_id"] for t in result], [2, 3, 1])
        self.assertEqual([t["rank"] for t in result], [1, 2, 3])

    def test_missing_standing_sorts_last_not_crash(self):
        teams = [team_row(1, standing=None), team_row(2, standing=1)]
        result = team_standings(teams)
        self.assertEqual([t["team_id"] for t in result], [2, 1])


class TestUpcomingMatchupPairs(unittest.TestCase):
    def test_collapses_both_directions_to_one_pair(self):
        pairs = [(1, 2), (2, 1), (3, 4), (4, 3)]
        result = upcoming_matchup_pairs(pairs)
        self.assertEqual(len(result), 2)
        self.assertIn((1, 2), result)
        self.assertIn((3, 4), result)


class TestTeamProjectedScore(unittest.TestCase):
    def test_sums_started_projections(self):
        rows = [
            row(1, 1, "QB", "QB", 0.0, projected_points=20.0),
            row(1, 2, "RB", "RB", 0.0, projected_points=12.5),
            row(1, 3, "RB", "BENCH", 0.0, projected_points=99.0),  # benched, excluded
        ]
        self.assertEqual(team_projected_score(rows), 32.5)

    def test_none_when_no_projections_available(self):
        rows = [row(1, 1, "QB", "QB", 0.0, projected_points=None)]
        self.assertIsNone(team_projected_score(rows))

    def test_skips_rows_missing_projection_rather_than_treating_as_zero(self):
        rows = [
            row(1, 1, "QB", "QB", 0.0, projected_points=20.0),
            row(1, 2, "RB", "RB", 0.0, projected_points=None),
        ]
        self.assertEqual(team_projected_score(rows), 20.0)


class TestNextWeekPreview(unittest.TestCase):
    def test_top_seed_clash_tagged_for_number_one_vs_two(self):
        standings = [standing_row(1, rank=1), standing_row(2, rank=2)]
        result = next_week_preview(standings, [(1, 2)], {})
        self.assertEqual(result[0]["tags"], ["top_seed_clash"])

    def test_standings_battle_tagged_for_close_ranks_not_extremes(self):
        # Ranks 1/2 are reserved for the more specific top_seed_clash tag
        # (tested separately above), so this uses ranks 3/4 for "close" and
        # 1/10 for "far apart" to isolate standings_battle on its own.
        standings = [
            standing_row(1, rank=1),
            standing_row(2, rank=3),
            standing_row(3, rank=4),
            standing_row(4, rank=9),
            standing_row(5, rank=10),
        ]
        result = next_week_preview(standings, [(2, 3), (1, 5)], {})
        by_pair = {frozenset((m["team_a"]["team_id"], m["team_b"]["team_id"])): m for m in result}
        self.assertIn("standings_battle", by_pair[frozenset((2, 3))]["tags"])
        self.assertNotIn("standings_battle", by_pair[frozenset((1, 5))]["tags"])
        self.assertNotIn("top_seed_clash", by_pair[frozenset((2, 3))]["tags"])

    def test_playoff_bubble_tagged_when_pct_in_doubt(self):
        standings = [standing_row(1, rank=5, playoff_pct=50.0), standing_row(2, rank=9, playoff_pct=2.0)]
        result = next_week_preview(standings, [(1, 2)], {})
        self.assertIn("playoff_bubble", result[0]["tags"])

    def test_no_playoff_bubble_tag_when_both_sides_are_locks(self):
        standings = [standing_row(1, rank=1, playoff_pct=99.0), standing_row(2, rank=2, playoff_pct=1.0)]
        result = next_week_preview(standings, [(1, 2)], {})
        self.assertNotIn("playoff_bubble", result[0]["tags"])

    def test_high_scoring_tagged_when_both_at_or_above_average(self):
        standings = [
            standing_row(1, rank=5),
            standing_row(2, rank=6),
            standing_row(3, rank=7),
            standing_row(4, rank=8),
        ]
        projected_scores = {1: 150.0, 2: 140.0, 3: 60.0, 4: 55.0}
        result = next_week_preview(standings, [(1, 2), (3, 4)], projected_scores)
        by_pair = {frozenset((m["team_a"]["team_id"], m["team_b"]["team_id"])): m for m in result}
        self.assertIn("high_scoring", by_pair[frozenset((1, 2))]["tags"])
        self.assertNotIn("high_scoring", by_pair[frozenset((3, 4))]["tags"])

    def test_sibling_matchup_tagged_from_owner_meta(self):
        standings = [standing_row(1, rank=5), standing_row(2, rank=6)]
        owner_meta = {1: {"sibling_team_id": 2, "location": "Dallas"}, 2: {"sibling_team_id": 1, "location": "Austin"}}
        result = next_week_preview(standings, [(1, 2)], {}, owner_meta)
        self.assertIn("sibling_matchup", result[0]["tags"])
        self.assertNotIn("same_city", result[0]["tags"])  # sibling takes priority over the same-city check

    def test_same_city_tagged_from_owner_meta(self):
        standings = [standing_row(1, rank=5), standing_row(2, rank=6)]
        owner_meta = {1: {"sibling_team_id": None, "location": "Houston"}, 2: {"sibling_team_id": None, "location": "Houston"}}
        result = next_week_preview(standings, [(1, 2)], {}, owner_meta)
        self.assertIn("same_city", result[0]["tags"])

    def test_missing_owner_meta_yields_no_family_or_city_tags(self):
        standings = [standing_row(1, rank=5), standing_row(2, rank=20)]  # far enough apart to avoid every other tag too
        result = next_week_preview(standings, [(1, 2)], {})
        self.assertEqual(result[0]["tags"], [])

    def test_sorted_most_tagged_first(self):
        # (1, 2) earns two tags (top_seed_clash + playoff_bubble); (3, 4)
        # earns only one (standings_battle) — listed first in the input but
        # expected to sort behind the more-tagged matchup.
        standings = [
            standing_row(1, rank=1, playoff_pct=50.0),
            standing_row(2, rank=2),
            standing_row(3, rank=9),
            standing_row(4, rank=10),
        ]
        result = next_week_preview(standings, [(3, 4), (1, 2)], {})
        self.assertEqual({result[0]["team_a"]["team_id"], result[0]["team_b"]["team_id"]}, {1, 2})
        self.assertEqual(len(result[0]["tags"]), 2)

    def test_untagged_matchup_still_included(self):
        standings = [standing_row(1, rank=1), standing_row(2, rank=10)]
        result = next_week_preview(standings, [(1, 2)], {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tags"], [])


if __name__ == "__main__":
    unittest.main()
