import unittest
from unittest.mock import MagicMock, patch

from ffassistant.connectors import espn


def fake_player(player_id, name, position, pro_team, injury_status="ACTIVE", lineup_slot=None):
    p = MagicMock()
    p.playerId = player_id
    p.name = name
    p.position = position
    p.proTeam = pro_team
    p.injuryStatus = injury_status
    p.lineupSlot = lineup_slot if lineup_slot is not None else position
    return p


def fake_team(
    team_id,
    team_name,
    waiver_rank,
    roster,
    points_for=None,
    points_against=None,
    playoff_pct=None,
    standing=None,
):
    t = MagicMock()
    t.team_id = team_id
    t.team_name = team_name
    t.waiver_rank = waiver_rank
    t.roster = roster
    # Explicitly set (rather than left to MagicMock's attribute auto-creation)
    # so a fixture that doesn't care about these gets real None, not a
    # truthy, unusable MagicMock standing in for "not synced".
    t.points_for = points_for
    t.points_against = points_against
    t.playoff_pct = playoff_pct
    t.standing = standing
    return t


def fake_box_player(player_id, name, position, pro_team, slot_position, points, game_date=None, projected_points=None):
    p = MagicMock()
    p.playerId = player_id
    p.name = name
    p.position = position
    p.proTeam = pro_team
    p.slot_position = slot_position
    p.points = points
    # Explicitly set (rather than left to MagicMock's attribute auto-creation)
    # so a fixture that doesn't care about these gets real None, not a
    # truthy, unusable MagicMock standing in for "no game_date".
    p.game_date = game_date
    p.projected_points = projected_points
    return p


def fake_box_score(home_team_id, home_lineup, away_team_id=None, away_lineup=None):
    m = MagicMock()
    home = MagicMock()
    home.team_id = home_team_id
    m.home_team = home
    m.home_lineup = home_lineup
    if away_team_id is None:
        m.away_team = None
        m.away_lineup = None
    else:
        away = MagicMock()
        away.team_id = away_team_id
        m.away_team = away
        m.away_lineup = away_lineup
    return m


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
                    fake_player(101, "Justin Jefferson", "WR", "MIN", lineup_slot="WR"),
                    fake_player(102, "Seattle Seahawks", "D/ST", "SEA", injury_status=None, lineup_slot="BE"),
                    fake_player(103, "Injured Guy", "RB", "KC", lineup_slot="IR"),
                ],
                points_for=950.5,
                points_against=800.0,
                playoff_pct=92.0,
                standing=1,
            )
        ]
        mock_connect.return_value = league

        teams = espn.get_teams(123, 2026)

        self.assertEqual(len(teams), 1)
        team = teams[0]
        self.assertEqual(team["platform_team_id"], "1")
        self.assertEqual(team["team_name"], "Keith's Team")
        self.assertEqual(team["waiver_priority"], 3)
        self.assertEqual(team["points_for"], 950.5)
        self.assertEqual(team["points_against"], 800.0)
        self.assertEqual(team["playoff_pct"], 92.0)
        self.assertEqual(team["standing"], 1)
        self.assertEqual(len(team["players"]), 3)
        self.assertEqual(team["players"][0]["full_name"], "Justin Jefferson")
        self.assertEqual(team["players"][0]["roster_status"], "starter")
        self.assertEqual(team["players"][1]["position"], "DST")  # mapped from 'D/ST'
        self.assertEqual(team["players"][1]["roster_status"], "bench")
        self.assertEqual(team["players"][2]["roster_status"], "ir")


class TestRosterStatus(unittest.TestCase):
    def test_be_is_bench(self):
        self.assertEqual(espn._roster_status("BE"), "bench")

    def test_ir_is_ir(self):
        self.assertEqual(espn._roster_status("IR"), "ir")

    def test_position_code_is_starter(self):
        self.assertEqual(espn._roster_status("QB"), "starter")
        self.assertEqual(espn._roster_status("RB/WR/TE"), "starter")

    def test_none_defaults_to_starter(self):
        self.assertEqual(espn._roster_status(None), "starter")


class TestGetBoxScores(unittest.TestCase):
    @patch("ffassistant.connectors.espn._connect")
    def test_maps_slot_names_and_both_sides(self, mock_connect):
        league = MagicMock()
        league.box_scores.return_value = [
            fake_box_score(
                home_team_id=1,
                home_lineup=[
                    fake_box_player(101, "Justin Jefferson", "WR", "MIN", "WR", 18.4),
                    fake_box_player(102, "Some Bench Guy", "RB", "NYJ", "BE", 6.1),
                    fake_box_player(103, "Seattle Seahawks", "D/ST", "SEA", "D/ST", 9.0),
                ],
                away_team_id=2,
                away_lineup=[
                    fake_box_player(201, "Flex Guy", "TE", "KC", "RB/WR/TE", 11.2),
                ],
            )
        ]
        mock_connect.return_value = league

        entries = espn.get_box_scores(123, 2026, 1)

        self.assertEqual(len(entries), 2)
        home = next(e for e in entries if e["platform_team_id"] == "1")
        away = next(e for e in entries if e["platform_team_id"] == "2")

        self.assertEqual(len(home["players"]), 3)
        self.assertEqual(home["players"][0]["slot_name"], "WR")
        self.assertEqual(home["players"][0]["points"], 18.4)
        self.assertEqual(home["players"][1]["slot_name"], "BENCH")  # mapped from 'BE'
        self.assertEqual(home["players"][2]["position"], "DST")  # mapped from 'D/ST'

        self.assertEqual(away["players"][0]["slot_name"], "FLEX")  # mapped from 'RB/WR/TE'

    @patch("ffassistant.connectors.espn._connect")
    def test_bye_week_only_yields_the_playing_side(self, mock_connect):
        league = MagicMock()
        league.box_scores.return_value = [
            fake_box_score(
                home_team_id=1,
                home_lineup=[fake_box_player(101, "Justin Jefferson", "WR", "MIN", "WR", 18.4)],
            )
        ]
        mock_connect.return_value = league

        entries = espn.get_box_scores(123, 2026, 1)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["platform_team_id"], "1")

    @patch("ffassistant.connectors.espn._connect")
    def test_captures_game_date_and_projected_points(self, mock_connect):
        import datetime

        kickoff = datetime.datetime(2025, 9, 7, 13, 0, 0)
        league = MagicMock()
        league.box_scores.return_value = [
            fake_box_score(
                home_team_id=1,
                home_lineup=[
                    fake_box_player(101, "Has A Game", "WR", "MIN", "WR", 18.4, game_date=kickoff, projected_points=14.2),
                    fake_box_player(102, "Bye Week Guy", "RB", "NYJ", "BE", 0.0),  # no game_date/projected_points
                ],
            )
        ]
        mock_connect.return_value = league

        entries = espn.get_box_scores(123, 2026, 1)
        players = entries[0]["players"]

        self.assertEqual(players[0]["game_date"], "2025-09-07T13:00:00")
        self.assertEqual(players[0]["projected_points"], 14.2)
        self.assertIsNone(players[1]["game_date"])
        self.assertIsNone(players[1]["projected_points"])


class TestGetFreeAgentScores(unittest.TestCase):
    @patch("ffassistant.connectors.espn._connect")
    def test_maps_fields_and_passes_week_and_size_through(self, mock_connect):
        league = MagicMock()
        league.free_agents.return_value = [
            fake_box_player(301, "Waiver Wire Hero", "RB", "DAL", "FA", 22.5, projected_points=11.2),
            fake_box_player(302, "Streaming DST", "D/ST", "SF", "FA", 14.0, projected_points=6.5),
        ]
        mock_connect.return_value = league

        entries = espn.get_free_agent_scores(123, 2026, week=3, size=250)

        league.free_agents.assert_called_once_with(week=3, size=250)
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0],
            {
                "source_player_id": "301",
                "full_name": "Waiver Wire Hero",
                "position": "RB",
                "nfl_team": "DAL",
                "points": 22.5,
                "projected_points": 11.2,
            },
        )
        self.assertEqual(entries[1]["position"], "DST")  # mapped from 'D/ST'

    @patch("ffassistant.connectors.espn._connect")
    def test_default_size_is_passed(self, mock_connect):
        league = MagicMock()
        league.free_agents.return_value = []
        mock_connect.return_value = league

        espn.get_free_agent_scores(123, 2026, week=3)

        league.free_agents.assert_called_once_with(week=3, size=300)


if __name__ == "__main__":
    unittest.main()
