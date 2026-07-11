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
        self.assertEqual(len(team["players"]), 3)

        purdy, lions, wilson = team["players"]
        self.assertEqual(purdy["position"], "QB")
        self.assertEqual(purdy["nfl_team"], "SF")
        self.assertEqual(purdy["injury_status"], "healthy")

        self.assertEqual(lions["position"], "DST")  # mapped from 'DEF'

        # selected_position of 'IR' (roster slot) shouldn't affect the actual
        # injury status, which comes from the separate 'status' field.
        self.assertEqual(wilson["injury_status"], "questionable")
        self.assertEqual(wilson["position"], "WR")


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
