import unittest
from unittest.mock import MagicMock, patch

from ffassistant.connectors import yahoo


class TestGetLeagueSettings(unittest.TestCase):
    @patch("ffassistant.connectors.yahoo._connect")
    def test_maps_slots_and_builds_scoring_from_stat_modifiers(self, mock_connect):
        league = MagicMock()
        league.league_id = "461.l.656302"
        league.settings.return_value = {
            "num_teams": "10",
            "stat_modifiers": {
                "stats": [
                    {"stat": {"stat_id": 5, "value": "4"}},
                    {"stat": {"stat_id": 6, "value": "-1"}},
                ]
            },
        }
        league.positions.return_value = {
            "QB": {"count": 1},
            "W/R/T": {"count": 1},
            "Q/W/R/T": {"count": 1},
            "DEF": {"count": 1},
            "BN": {"count": 5},
            "IR": {"count": 1},
        }
        league.yhandler.get_settings_raw.return_value = {
            "fantasy_content": {
                "league": [
                    {},
                    {
                        "settings": [
                            {
                                "stat_categories": {
                                    "stats": [
                                        {"stat": {"stat_id": 5, "display_name": "Pass TD"}},
                                        {"stat": {"stat_id": 6, "display_name": "Int"}},
                                    ]
                                }
                            }
                        ]
                    },
                ]
            }
        }
        mock_connect.return_value = league

        settings = yahoo.get_league_settings("461.l.656302")

        self.assertEqual(settings["team_count"], 10)
        self.assertEqual(settings["scoring"], {"pass_td": 4.0, "int": -1.0})
        self.assertEqual(
            settings["roster_slots"],
            {"QB": 1, "FLEX": 1, "SUPER_FLEX": 1, "DST": 1, "BENCH": 5, "IR": 1},
        )


class TestGetTeams(unittest.TestCase):
    @patch("ffassistant.connectors.yahoo._connect")
    def test_resolves_teams_players_and_pro_teams(self, mock_connect):
        league = MagicMock()
        league.teams.return_value = {
            "461.l.656302.t.5": {"team_id": "5", "name": "Long Balls", "waiver_priority": 9},
        }
        league.standings.return_value = [
            {
                "team_key": "461.l.656302.t.5",
                "outcome_totals": {"wins": 1, "losses": 0, "ties": 0},
                "points_for": "135.3",
                "points_against": "92.18",
            }
        ]

        team_obj = MagicMock()
        team_obj.roster.return_value = [
            {
                "player_id": 34218,
                "name": "Brock Purdy",
                "status": "",
                "position_type": "O",
                "eligible_positions": ["QB", "Q/W/R/T"],
                "selected_position": "QB",
            },
            {
                "player_id": 100008,
                "name": "Lions",
                "status": "",
                "position_type": "DT",
                "eligible_positions": ["DEF"],
                "selected_position": "DEF",
            },
            {
                "player_id": 33965,
                "name": "Garrett Wilson",
                "status": "Q",
                "position_type": "O",
                "eligible_positions": ["WR", "W/R/T", "Q/W/R/T"],
                "selected_position": "IR",
            },
        ]
        league.to_team.return_value = team_obj
        league.player_details.return_value = [
            {"player_id": "34218", "editorial_team_abbr": "SF"},
            {"player_id": "100008", "editorial_team_abbr": "Det"},
            {"player_id": "33965", "editorial_team_abbr": "NYJ"},
        ]
        mock_connect.return_value = league

        teams = yahoo.get_teams("461.l.656302")

        self.assertEqual(len(teams), 1)
        team = teams[0]
        self.assertEqual(team["platform_team_id"], "5")
        self.assertEqual(team["team_name"], "Long Balls")
        self.assertEqual(team["waiver_priority"], 9)
        self.assertEqual(team["wins"], 1)
        self.assertEqual(team["losses"], 0)
        self.assertEqual(team["points_for"], 135.3)
        self.assertEqual(team["points_against"], 92.18)
        self.assertEqual(len(team["players"]), 3)

        purdy, lions, wilson = team["players"]
        self.assertEqual(purdy["position"], "QB")
        self.assertEqual(purdy["nfl_team"], "SF")
        self.assertEqual(purdy["injury_status"], "healthy")
        self.assertEqual(purdy["roster_status"], "starter")

        self.assertEqual(lions["position"], "DST")  # mapped from 'DEF'
        self.assertEqual(lions["roster_status"], "starter")

        # selected_position of 'IR' (roster slot) shouldn't affect the actual
        # injury status, which comes from the separate 'status' field.
        self.assertEqual(wilson["injury_status"], "questionable")
        self.assertEqual(wilson["position"], "WR")
        self.assertEqual(wilson["roster_status"], "ir")

    @patch("ffassistant.connectors.yahoo._connect")
    def test_guillotine_style_standings_has_no_outcome_totals_or_points_against(self, mock_connect):
        # A Guillotine league has no head-to-head record to track (lowest
        # scorer is eliminated each week) — its standings() entries carry
        # points_for but no "outcome_totals"/"points_against" at all.
        league = MagicMock()
        league.teams.return_value = {
            "470.l.124095.t.4": {"team_id": "4", "name": "The Guillo-team", "waiver_priority": None},
        }
        league.standings.return_value = [
            {"team_key": "470.l.124095.t.4", "name": "The Guillo-team", "points_for": "92.18"},
        ]
        league.to_team.return_value.roster.return_value = []
        league.player_details.return_value = []
        mock_connect.return_value = league

        teams = yahoo.get_teams("470.l.124095")

        team = teams[0]
        self.assertIsNone(team["wins"])
        self.assertIsNone(team["losses"])
        self.assertEqual(team["points_for"], 92.18)
        self.assertIsNone(team["points_against"])


def _fake_matchups_raw(matchup_pairs):
    """matchup_pairs: list of (team_id_a, points_a, team_id_b, points_b),
    shaped like the real per-matchup 'teams' block confirmed live against
    Yahoo's API (see ffassistant.connectors.yahoo.get_matchups)."""
    matchups = {"count": len(matchup_pairs)}
    for i, (team_a, points_a, team_b, points_b) in enumerate(matchup_pairs):
        matchups[str(i)] = {
            "matchup": {
                "0": {
                    "teams": {
                        "count": 2,
                        "0": {"team": [[{"team_id": team_a}], {"team_points": {"coverage_type": "week", "total": points_a}}]},
                        "1": {"team": [[{"team_id": team_b}], {"team_points": {"coverage_type": "week", "total": points_b}}]},
                    }
                }
            }
        }
    return {"fantasy_content": {"league": [{}, {"scoreboard": {"0": {"matchups": matchups}}}]}}


class TestGetMatchups(unittest.TestCase):
    @patch("ffassistant.connectors.yahoo._connect")
    def test_pairs_both_sides_with_that_weeks_score(self, mock_connect):
        league = MagicMock()
        league.matchups.return_value = _fake_matchups_raw([("1", "104.38", "2", "84.26")])
        mock_connect.return_value = league

        pairs = yahoo.get_matchups("461.l.656302", 2)

        self.assertEqual(
            pairs,
            [
                {"platform_team_id": "1", "opponent_platform_team_id": "2", "points_for": 104.38, "points_against": 84.26},
                {"platform_team_id": "2", "opponent_platform_team_id": "1", "points_for": 84.26, "points_against": 104.38},
            ],
        )


class TestRosterStatus(unittest.TestCase):
    def test_bn_is_bench(self):
        self.assertEqual(yahoo._roster_status("BN"), "bench")

    def test_ir_prefixed_codes_are_ir(self):
        self.assertEqual(yahoo._roster_status("IR"), "ir")
        self.assertEqual(yahoo._roster_status("IR+"), "ir")

    def test_position_code_is_starter(self):
        self.assertEqual(yahoo._roster_status("QB"), "starter")
        self.assertEqual(yahoo._roster_status("W/R/T"), "starter")

    def test_none_defaults_to_starter(self):
        self.assertEqual(yahoo._roster_status(None), "starter")


class TestListLeagueIds(unittest.TestCase):
    @patch("ffassistant.connectors.yahoo._connect_game")
    def test_returns_league_keys_for_season(self, mock_connect_game):
        game = MagicMock()
        game.league_ids.return_value = ["470.l.124095", "470.l.150416"]
        mock_connect_game.return_value = game

        ids = yahoo.list_league_ids(season=2026)

        self.assertEqual(ids, ["470.l.124095", "470.l.150416"])
        game.league_ids.assert_called_once_with(year=2026)


if __name__ == "__main__":
    unittest.main()
