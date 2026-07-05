import unittest
from unittest.mock import MagicMock, patch

from ffassistant.connectors import espn


def fake_player(player_id, name, position, pro_team, injury_status="ACTIVE"):
    p = MagicMock()
    p.playerId = player_id
    p.name = name
    p.position = position
    p.proTeam = pro_team
    p.injuryStatus = injury_status
    return p


def fake_team(team_id, team_name, waiver_rank, roster):
    t = MagicMock()
    t.team_id = team_id
    t.team_name = team_name
    t.waiver_rank = waiver_rank
    t.roster = roster
    return t


class TestGetLeagueSettings(unittest.TestCase):
    @patch("ffassistant.connectors.espn._connect")
    def test_maps_slot_names_and_filters_zero_scoring(self, mock_connect):
        league = MagicMock()
        league.settings.team_count = 10
        league.settings.position_slot_counts = {
            "QB": 1,
            "RB": 2,
            "WR": 2,
            "TE": 1,
            "RB/WR/TE": 1,
            "D/ST": 1,
            "K": 1,
            "BE": 6,
            "IR": 1,
            "OP": 0,  # unused slot type, should be dropped
        }
        league.settings.scoring_format = [
            {"abbr": "PTD", "label": "TD Pass", "points": 4},
            {"abbr": "PA", "label": "Pass Attempt", "points": 0},  # zero -> excluded
        ]
        mock_connect.return_value = league

        settings = espn.get_league_settings(123, 2026)

        self.assertEqual(settings["team_count"], 10)
        self.assertEqual(settings["scoring"], {"PTD": 4})
        self.assertEqual(
            settings["roster_slots"],
            {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BENCH": 6, "IR": 1},
        )


class TestGetTeams(unittest.TestCase):
    @patch("ffassistant.connectors.espn._connect")
    def test_resolves_teams_and_players(self, mock_connect):
        league = MagicMock()
        league.teams = [
            fake_team(
                1,
                "Keith's Team",
                waiver_rank=3,
                roster=[
                    fake_player(101, "Justin Jefferson", "WR", "MIN"),
                    fake_player(102, "Seattle Seahawks", "D/ST", "SEA", injury_status=None),
                ],
            )
        ]
        mock_connect.return_value = league

        teams = espn.get_teams(123, 2026)

        self.assertEqual(len(teams), 1)
        team = teams[0]
        self.assertEqual(team["platform_team_id"], "1")
        self.assertEqual(team["team_name"], "Keith's Team")
        self.assertEqual(team["waiver_priority"], 3)
        self.assertEqual(len(team["players"]), 2)
        self.assertEqual(team["players"][0]["full_name"], "Justin Jefferson")
        self.assertEqual(team["players"][1]["position"], "DST")  # mapped from 'D/ST'


if __name__ == "__main__":
    unittest.main()
