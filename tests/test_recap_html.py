import unittest

from ffassistant.recap_html import render_recap_html

BASE_DATA = {
    "league_id": 3,
    "season": 2025,
    "week": 1,
    "team_names": {},
    "team_scores": {},
    "high_low": {"highest": None, "lowest": None},
    "matchups": [],
    "matchup_details": [],
    "biggest_closest": {"biggest_win": None, "closest_matchup": None},
    "top_performers": {},
    "best_by_slot": {},
    "optimal_lineup_by_team": {},
    "gaffes_by_team": {},
    "waiver_wire": [],
    "standings": [],
    "next_week": {"week": 2, "matchups": []},
}


def merged(**overrides) -> dict:
    data = {**BASE_DATA}
    data.update(overrides)
    return data


class TestEmptyWeek(unittest.TestCase):
    def test_renders_without_error_and_flags_missing_data(self):
        html_out = render_recap_html(merged(), league_name="TAMS")
        self.assertIn("<!doctype html>", html_out)
        self.assertIn("TAMS", html_out)
        self.assertIn("Week 1 Recap", html_out)
        self.assertIn("No box scores synced for this week yet.", html_out)
        # Waiver section always renders, synced or not
        self.assertIn("Waiver Wire Watch", html_out)
        self.assertIn("Nobody&#x27;s synced this week&#x27;s free-agent scores yet", html_out)

    def test_waiver_wire_renders_picks_with_comparison(self):
        html_out = render_recap_html(
            merged(
                waiver_wire=[
                    {
                        "player_id": 1,
                        "full_name": "Waiver Steal",
                        "position": "RB",
                        "points": 22.0,
                        "beat_lowest_starter_at_position": True,
                        "lowest_starter_points": 6.0,
                    },
                    {
                        "player_id": 2,
                        "full_name": "Fine I Guess",
                        "position": "WR",
                        "points": 8.0,
                        "beat_lowest_starter_at_position": False,
                        "lowest_starter_points": None,
                    },
                ]
            )
        )
        self.assertIn("Waiver Steal", html_out)
        self.assertIn("more than every started RB", html_out)
        self.assertIn("Fine I Guess", html_out)
        self.assertIn("somebody out there should've been paying attention", html_out)

    def test_header_has_bot_persona(self):
        html_out = render_recap_html(merged(), league_name="TAMS")
        self.assertIn("TAMS Fantasybot", html_out)
        self.assertIn("Beep boop.", html_out)


class TestStandings(unittest.TestCase):
    def test_ranks_teams_and_badges_high_low(self):
        data = merged(
            team_names={1: "Team One", 2: "Team Two", 3: "Team Three"},
            team_scores={1: 100.0, 2: 130.0, 3: 80.0},
            high_low={
                "highest": {"team_id": 2, "team_name": "Team Two", "points": 130.0},
                "lowest": {"team_id": 3, "team_name": "Team Three", "points": 80.0},
            },
        )
        html_out = render_recap_html(data)
        self.assertIn("Top Score", html_out)
        self.assertIn("Bottom of the Barrel", html_out)
        # Team Two (highest) should appear before Team One before Team Three in the table
        self.assertLess(html_out.index("Team Two"), html_out.index("Team One"))
        self.assertLess(html_out.index("Team One"), html_out.index("Team Three"))

    def test_shows_real_team_name_alongside_owner_nickname(self):
        data = merged(
            team_names={1: "KB"},
            team_real_names={1: "Bijan'd meAt"},
            team_scores={1: 100.0},
            high_low={"highest": {"team_id": 1, "team_name": "KB", "points": 100.0}, "lowest": None},
        )
        html_out = render_recap_html(data)
        self.assertIn("Bijan&#x27;d meAt", html_out)  # html.escape also escapes the apostrophe
        self.assertIn('<span class="owner-tag">(KB)</span>', html_out)


def _matchup_detail_fixture(**overrides) -> dict:
    base = {
        "team_a": {"team_id": 1, "team_name": "Nail A", "points": 100.0},
        "team_b": {"team_id": 2, "team_name": "Nail B", "points": 100.4},
        "margin": 0.4,
        "is_matchup_of_the_week": True,
        "team_a_detail": {"score_by_checkpoint": [], "top_players": [], "performance_vs_projection": []},
        "team_b_detail": {"score_by_checkpoint": [], "top_players": [], "performance_vs_projection": []},
    }
    base.update(overrides)
    return base


class TestMatchupTabs(unittest.TestCase):
    def test_empty_matchup_details_shows_not_synced_message(self):
        html_out = render_recap_html(merged())
        self.assertIn("Matchup Stories", html_out)
        self.assertIn("No matchup pairings synced for this week yet", html_out)

    def test_renders_one_tab_per_matchup_with_matchup_of_the_week_first(self):
        # matchup_details() always orders the closest-margin matchup first — mirror that ordering here.
        details = [
            _matchup_detail_fixture(),  # the 0.4-margin nailbiter, is_matchup_of_the_week=True
            _matchup_detail_fixture(
                team_a={"team_id": 1, "team_name": "Blowout Winner", "points": 150.0},
                team_b={"team_id": 2, "team_name": "Blowout Loser", "points": 60.0},
                margin=90.0,
                is_matchup_of_the_week=False,
            ),
        ]
        html_out = render_recap_html(merged(matchup_details=details))
        self.assertIn("Matchup Stories", html_out)
        self.assertIn("Nail A vs Nail B", html_out)
        self.assertIn("Blowout Winner vs Blowout Loser", html_out)
        self.assertIn("⭐", html_out)  # matchup of the week badge
        self.assertIn("💥", html_out)  # biggest blowout badge
        self.assertIn("coin flip", html_out)  # nailbiter flavor for the 0.4-margin matchup
        self.assertIn("massacre", html_out)  # blowout flavor for the 90.0-margin matchup
        # First matchup's tab is checked by default (matchup of the week shown first)
        self.assertIn('id="matchup-tab-0" class="matchup-tab-input" checked', html_out)

    def test_renders_top_players_and_projection_surprises_per_side(self):
        details = [
            _matchup_detail_fixture(
                team_a_detail={
                    "score_by_checkpoint": [],
                    "top_players": [{"player_id": 1, "full_name": "Side A Stud", "position": "RB", "points": 30.0}],
                    "performance_vs_projection": [
                        {"player_id": 1, "full_name": "Side A Stud", "points": 30.0, "projected_points": 12.0, "delta": 18.0, "tag": "over"}
                    ],
                },
                team_b_detail={
                    "score_by_checkpoint": [],
                    "top_players": [{"player_id": 2, "full_name": "Side B Bust", "position": "WR", "points": 2.0}],
                    "performance_vs_projection": [
                        {"player_id": 2, "full_name": "Side B Bust", "points": 2.0, "projected_points": 15.0, "delta": -13.0, "tag": "under"}
                    ],
                },
            )
        ]
        html_out = render_recap_html(merged(matchup_details=details))
        self.assertIn("Side A Stud", html_out)
        self.assertIn("went off for", html_out)
        self.assertIn("Side B Bust", html_out)
        self.assertIn("no-showed at", html_out)

    def test_renders_checkpoint_chart_when_enough_windows(self):
        details = [
            _matchup_detail_fixture(
                team_a_detail={
                    "score_by_checkpoint": [
                        {"window": "Sunday Afternoon", "points_this_window": 40.0, "cumulative_points": 40.0, "players": []},
                        {"window": "Sunday Night", "points_this_window": 10.0, "cumulative_points": 50.0, "players": []},
                    ],
                    "top_players": [],
                    "performance_vs_projection": [],
                },
                team_b_detail={
                    "score_by_checkpoint": [
                        {"window": "Sunday Afternoon", "points_this_window": 30.0, "cumulative_points": 30.0, "players": []},
                    ],
                    "top_players": [],
                    "performance_vs_projection": [],
                },
            )
        ]
        html_out = render_recap_html(merged(matchup_details=details))
        self.assertIn('class="checkpoint-chart"', html_out)
        self.assertIn("Sun PM", html_out)
        self.assertNotIn("Not enough game-time data", html_out)

    def test_renders_narrative_when_present(self):
        details = [_matchup_detail_fixture(narrative="A back-and-forth thriller decided on Monday night.")]
        html_out = render_recap_html(merged(matchup_details=details))
        self.assertIn("A back-and-forth thriller decided on Monday night.", html_out)

    def test_real_team_name_shown_alongside_owner_name_in_header_and_sides(self):
        details = [
            _matchup_detail_fixture(
                team_a={"team_id": 1, "team_name": "KB", "points": 100.0},
                team_b={"team_id": 2, "team_name": "Shiny", "points": 90.0},
            )
        ]
        html_out = render_recap_html(
            merged(matchup_details=details, team_real_names={1: "Bijan'd meAt", 2: "Josh.0"})
        )
        self.assertIn("Bijan&#x27;d meAt", html_out)
        self.assertIn("Josh.0", html_out)
        self.assertIn('<span class="owner-tag">(KB)</span>', html_out)
        self.assertIn('<span class="owner-tag">(Shiny)</span>', html_out)

    def test_side_subheads_carry_emoji(self):
        details = [
            _matchup_detail_fixture(
                team_a_detail={
                    "score_by_checkpoint": [],
                    "top_players": [{"player_id": 1, "full_name": "Guy One", "position": "RB", "points": 10.0}],
                    "performance_vs_projection": [
                        {"player_id": 1, "full_name": "Guy One", "points": 10.0, "projected_points": 2.0, "delta": 8.0, "tag": "over"}
                    ],
                },
                team_b_detail={"score_by_checkpoint": [], "top_players": [], "performance_vs_projection": []},
            )
        ]
        html_out = render_recap_html(merged(matchup_details=details))
        self.assertIn("🌟 Top Players", html_out)
        self.assertIn("😲 Surprises", html_out)


class TestTopPerformersAndSlots(unittest.TestCase):
    def test_top_performers_grouped_by_position_in_order(self):
        data = merged(
            top_performers={
                "RB": [{"player_id": 1, "full_name": "Best RB", "team_name": "T1", "points": 30.0}],
                "QB": [{"player_id": 2, "full_name": "Best QB", "team_name": "T2", "points": 28.0}],
            }
        )
        html_out = render_recap_html(data)
        # QB comes before RB per POSITION_ORDER despite dict insertion order
        self.assertLess(html_out.index("Best QB"), html_out.index("Best RB"))

    def test_best_by_slot_renders_bench_award(self):
        data = merged(
            best_by_slot={
                "QB": None,
                "RB": None,
                "WR": None,
                "TE": None,
                "DST": None,
                "K": None,
                "BENCH": {"team_id": 1, "team_name": "Deep Bench Squad", "points": 45.0},
            }
        )
        html_out = render_recap_html(data)
        self.assertIn("Best Bench", html_out)
        self.assertIn("Deep Bench Squad", html_out)

    def test_best_by_slot_lists_contributing_players_with_colored_points(self):
        data = merged(
            best_by_slot={
                "QB": None,
                "RB": {
                    "team_id": 1,
                    "team_name": "RB Stack",
                    "points": 35.0,
                    "players": [
                        {"player_id": 1, "full_name": "Dedicated RB", "points": 10.0},
                        {"player_id": 2, "full_name": "Flexed RB", "points": 25.0},
                    ],
                },
                "WR": None,
                "TE": None,
                "DST": None,
                "K": None,
                "BENCH": None,
            }
        )
        html_out = render_recap_html(data)
        self.assertIn("Flexed RB (25.0)", html_out)
        self.assertIn("Dedicated RB (10.0)", html_out)
        self.assertIn("Dedicated RB (10.0)<br>Flexed RB (25.0)", html_out)  # one contributor per line, in list order
        self.assertIn('style="color:#2b5ea8"', html_out)  # RB position color on the points line

    def test_bench_contributors_also_get_line_breaks(self):
        data = merged(
            best_by_slot={
                "QB": None,
                "RB": None,
                "WR": None,
                "TE": None,
                "DST": None,
                "K": None,
                "BENCH": {
                    "team_id": 1,
                    "team_name": "Deep Bench Squad",
                    "points": 60.0,
                    "players": [
                        {"player_id": 1, "full_name": "Bench Guy One", "points": 30.0},
                        {"player_id": 2, "full_name": "Bench Guy Two", "points": 20.0},
                        {"player_id": 3, "full_name": "Bench Guy Three", "points": 10.0},
                    ],
                },
            }
        )
        html_out = render_recap_html(data)
        self.assertIn("Bench Guy One (30.0)<br>Bench Guy Two (20.0)<br>Bench Guy Three (10.0)", html_out)


class TestOptimalLineup(unittest.TestCase):
    def test_best_efficiency_sorts_first(self):
        data = merged(
            team_names={1: "Efficient", 2: "Disaster"},
            optimal_lineup_by_team={
                1: {"actual_points": 100.0, "optimal_points": 100.0, "pct": 100.0},
                2: {"actual_points": 40.0, "optimal_points": 100.0, "pct": 40.0},
            },
        )
        html_out = render_recap_html(data)
        self.assertLess(html_out.index("Efficient"), html_out.index("Disaster"))
        self.assertIn("Self-Inflicted Disaster", html_out)
        self.assertIn("Lineup Perfection", html_out)

    def test_none_pct_sorts_last_even_though_best_first(self):
        data = merged(
            team_names={1: "Has Data", 2: "No Data"},
            optimal_lineup_by_team={
                1: {"actual_points": 50.0, "optimal_points": 100.0, "pct": 50.0},
                2: {"actual_points": 0, "optimal_points": 0, "pct": None},
            },
        )
        html_out = render_recap_html(data)
        self.assertLess(html_out.index("Has Data"), html_out.index("No Data"))

    def test_none_pct_renders_dash_not_crash(self):
        data = merged(
            team_names={1: "No Data Team"},
            optimal_lineup_by_team={1: {"actual_points": 0, "optimal_points": 0, "pct": None}},
        )
        html_out = render_recap_html(data)
        self.assertIn("—", html_out)
        self.assertIn("No data", html_out)


class TestGaffes(unittest.TestCase):
    def test_renders_worst_gaffes_sorted_and_capped_at_five(self):
        gaffes_by_team = {
            1: [
                {
                    "started": {"player_id": 10, "full_name": "Small Bust", "points": 4.0},
                    "benched": {"player_id": 11, "full_name": "Small Sleeper", "points": 10.0},
                    "missed_points": 6.0,
                }
            ],
            2: [
                {
                    "started": {"player_id": 20, "full_name": "Huge Bust", "points": 1.0},
                    "benched": {"player_id": 21, "full_name": "Huge Sleeper", "points": 40.0},
                    "missed_points": 39.0,
                }
            ],
        }
        data = merged(team_names={1: "Team A", 2: "Team B"}, gaffes_by_team=gaffes_by_team)
        html_out = render_recap_html(data)
        self.assertLess(html_out.index("Huge Bust"), html_out.index("Small Bust"))
        self.assertIn("🍆 Boners of the Week", html_out)
        self.assertNotIn("Gaffe of the Week", html_out)
        self.assertNotIn("🚨", html_out)

    def test_no_gaffes_renders_positive_message(self):
        html_out = render_recap_html(merged())
        self.assertIn("Nobody made a start/sit mistake", html_out)
        self.assertIn("🍆 Boners of the Week", html_out)


class TestEscaping(unittest.TestCase):
    def test_team_names_are_html_escaped(self):
        data = merged(
            team_names={1: "<script>alert(1)</script>", 2: "Safe Team"},
            team_scores={1: 100.0, 2: 90.0},
            high_low={
                "highest": {"team_id": 1, "team_name": "<script>alert(1)</script>", "points": 100.0},
                "lowest": {"team_id": 2, "team_name": "Safe Team", "points": 90.0},
            },
        )
        html_out = render_recap_html(data, league_name="<b>Injected</b>")
        self.assertNotIn("<script>alert(1)</script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertNotIn("<b>Injected</b>", html_out)
        self.assertIn("&lt;b&gt;Injected&lt;/b&gt;", html_out)


def _standing_fixture(
    team_id, rank, team_name=None, wins=8, losses=2, ties=0, points_for=900.0, playoff_pct=75.0, team_real_name=None
):
    return {
        "team_id": team_id,
        "team_name": team_name or f"Team {team_id}",
        "team_real_name": team_real_name,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "points_for": points_for,
        "points_against": None,
        "playoff_pct": playoff_pct,
        "standing": rank,
        "rank": rank,
    }


class TestNextWeekPreviewSection(unittest.TestCase):
    def test_empty_standings_and_matchups_show_not_synced_notes(self):
        html_out = render_recap_html(merged())
        self.assertIn("Week 2 Preview", html_out)
        self.assertIn("No standings synced for this league yet.", html_out)
        self.assertIn("Next week's matchup pairings haven't been synced yet", html_out)

    def test_heading_uses_next_week_number(self):
        html_out = render_recap_html(merged(next_week={"week": 5, "matchups": []}))
        self.assertIn("Week 5 Preview", html_out)

    def test_standings_table_renders_rank_record_and_playoff_pct(self):
        standings = [
            _standing_fixture(1, rank=1, team_name="Front Runner", wins=9, losses=1, playoff_pct=98.0, points_for=1000.5),
            _standing_fixture(2, rank=2, team_name="Chaser", wins=7, losses=3, playoff_pct=60.0),
        ]
        html_out = render_recap_html(merged(standings=standings))
        self.assertLess(html_out.index("Front Runner"), html_out.index("Chaser"))
        self.assertIn("9-1", html_out)
        self.assertIn("98%", html_out)
        self.assertIn("1000.5", html_out)

    def test_standings_row_shows_real_team_name_alongside_owner_name(self):
        standings = [_standing_fixture(1, rank=1, team_name="KB", team_real_name="Bijan'd meAt")]
        html_out = render_recap_html(merged(standings=standings))
        self.assertIn("Bijan&#x27;d meAt", html_out)
        self.assertIn('<span class="owner-tag">(KB)</span>', html_out)

    def test_standings_row_with_no_record_renders_dash(self):
        standings = [_standing_fixture(1, rank=1, wins=None, losses=None, playoff_pct=None, points_for=None)]
        html_out = render_recap_html(merged(standings=standings))
        self.assertIn("—", html_out)

    def test_next_week_matchup_renders_tag_badges(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "Top Dog", "rank": 1, "wins": 9, "losses": 1, "projected_score": 140.0},
                "team_b": {"team_id": 2, "team_name": "Runner Up", "rank": 2, "wins": 8, "losses": 2, "projected_score": 135.0},
                "tags": ["top_seed_clash", "high_scoring"],
            }
        ]
        html_out = render_recap_html(merged(next_week={"week": 3, "matchups": matchups}))
        self.assertIn("Top Dog", html_out)
        self.assertIn("Runner Up", html_out)
        self.assertIn("Clash of the Titans", html_out)
        self.assertIn("Potential Shootout", html_out)
        self.assertIn("proj. 140.0", html_out)

    def test_next_week_matchup_shows_real_team_name_alongside_owner_name(self):
        matchups = [
            {
                "team_a": {
                    "team_id": 1, "team_name": "KB", "team_real_name": "Bijan'd meAt",
                    "rank": 1, "wins": 9, "losses": 1, "projected_score": None,
                },
                "team_b": {
                    "team_id": 2, "team_name": "Shiny", "team_real_name": "Josh.0",
                    "rank": 2, "wins": 8, "losses": 2, "projected_score": None,
                },
                "tags": [],
            }
        ]
        html_out = render_recap_html(merged(next_week={"week": 3, "matchups": matchups}))
        self.assertIn("Bijan&#x27;d meAt", html_out)
        self.assertIn('<span class="owner-tag">(KB)</span>', html_out)
        self.assertIn("Josh.0", html_out)

    def test_untagged_matchup_renders_without_badges(self):
        matchups = [
            {
                "team_a": {"team_id": 1, "team_name": "A", "rank": 3, "wins": 5, "losses": 5, "projected_score": None},
                "team_b": {"team_id": 2, "team_name": "B", "rank": 9, "wins": 2, "losses": 8, "projected_score": None},
                "tags": [],
            }
        ]
        html_out = render_recap_html(merged(next_week={"week": 3, "matchups": matchups}))
        self.assertIn('<div class="nw-matchup">', html_out)
        self.assertNotIn('<div class="nw-tags">', html_out)


if __name__ == "__main__":
    unittest.main()
