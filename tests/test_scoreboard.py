import sqlite3
import unittest
from unittest.mock import patch

from ffassistant.scoreboard import build_side, computed_live_projection, parse_nfl_games
from tests.test_api import ApiTestCase


def event(home, away, state, period=0, clock=0.0, detail=""):
    return {
        "competitions": [
            {
                "status": {"period": period, "clock": clock, "type": {"state": state, "shortDetail": detail}},
                "competitors": [{"team": {"abbreviation": home}}, {"team": {"abbreviation": away}}],
            }
        ]
    }


NFL = {
    "events": [
        event("DAL", "TB", "post", 4, 0, "Final"),
        event("GB", "CHI", "in", 3, 450.0, "5:12 - 3rd"),  # half of Q3 left -> 1.5 quarters of 4
        event("WSH", "PHI", "pre", detail="1:00 PM"),
    ]
}


def starter(name, team, points, projected):
    return {"full_name": name, "position": "WR", "nfl_team": team, "points": points, "projected": projected}


class TestParseNflGames(unittest.TestCase):
    def test_states_and_remaining_fraction(self):
        games = parse_nfl_games(NFL)
        self.assertEqual(games["DAL"]["remaining_fraction"], 0.0)
        self.assertEqual(games["CHI"]["state"], "in")
        self.assertAlmostEqual(games["GB"]["remaining_fraction"], (900 + 450) / 3600)
        self.assertEqual(games["PHI"]["remaining_fraction"], 1.0)

    def test_team_codes_canonicalized(self):
        # ESPN's public scoreboard already says WSH, but any platform spelling must join.
        games = parse_nfl_games({"events": [event("WAS", "LA", "pre")]})
        self.assertIn("WSH", games)
        self.assertIn("LAR", games)

    def test_overtime_has_nothing_left(self):
        games = parse_nfl_games({"events": [event("KC", "BUF", "in", 5, 300.0)]})
        self.assertEqual(games["KC"]["remaining_fraction"], 0.0)


class TestComputedLiveProjection(unittest.TestCase):
    def test_blends_actual_and_projected_by_game_state(self):
        games = parse_nfl_games(NFL)
        starters = [
            starter("Done", "DAL", 20.0, 10.0),      # final -> 20
            starter("Live", "GB", 6.0, 12.0),        # 6 + 12 * 0.375 -> 10.5
            starter("Later", "Was", 0.0, 15.0),      # Yahoo title-case, not started -> 15
            starter("Bye", "MIA", 0.0, None),        # no game -> 0
        ]
        self.assertEqual(computed_live_projection(starters, games), 45.5)

    def test_none_without_projections_or_games(self):
        games = parse_nfl_games(NFL)
        self.assertIsNone(computed_live_projection([starter("A", "DAL", 5.0, None)], games))
        self.assertIsNone(computed_live_projection([starter("A", "DAL", 5.0, 9.0)], {}))


class TestBuildSide(unittest.TestCase):
    def test_platform_figures_win_over_computed(self):
        side = {
            "platform_team_id": "1", "score": 26.0, "projected": 120.0, "live_projected": 130.0,
            "starters": [starter("A", "DAL", 26.0, 10.0)],
        }
        built = build_side(side, parse_nfl_games(NFL))
        self.assertEqual((built["projected"], built["live_projected"]), (120.0, 130.0))

    def test_fallbacks_and_playing_now(self):
        side = {
            "platform_team_id": "1", "score": 12.0, "projected": None, "live_projected": None,
            "starters": [
                starter("Low", "GB", 2.0, 10.0),
                starter("High", "CHI", 10.0, 10.0),
                starter("Later", "PHI", 0.0, 15.0),
                starter("Done", "DAL", 0.0, 5.0),
            ],
        }
        built = build_side(side, parse_nfl_games(NFL))
        self.assertEqual(built["projected"], 40.0)
        self.assertEqual(built["live_projected"], 34.5)  # 2+3.75 + 10+3.75 + 15 + 0
        self.assertEqual([p["full_name"] for p in built["playing_now"]], ["High", "Low"])
        self.assertEqual((built["yet_to_play"], built["done"]), (1, 1))
        self.assertEqual(built["playing_now"][0]["game_detail"], "5:12 - 3rd")


class TestScoreboardApi(ApiTestCase):
    """/api/scoreboard — base seed's league 1 is Sleeper with team 1 mine;
    platform calls are mocked, nothing touches the network."""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE leagues SET platform_league_id = 'abc' WHERE league_id = 1")
        conn.execute("UPDATE teams SET platform_team_id = CAST(team_id AS TEXT) WHERE league_id = 1")
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, platform_league_id, team_count, active) "
            "VALUES (2, 'Broken League', 'espn', '999', 2, 1)"
        )
        conn.execute("INSERT INTO teams (team_id, league_id, platform_team_id, team_name, is_mine) VALUES (20, 2, '1', 'Mine', 1)")
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (3, 'Manual League', 'manual', 2, 1)"
        )
        conn.execute("INSERT INTO teams (team_id, league_id, team_name, is_mine) VALUES (30, 3, 'Mine', 1)")
        conn.commit()
        conn.close()

    def _fake_fetch(self, league, season, week):
        if league["platform"] == "espn":
            raise RuntimeError("cookie expired")
        side = lambda tid, score: {  # noqa: E731
            "platform_team_id": tid, "score": score, "projected": None, "live_projected": None,
            "starters": [starter("Pickens", "DAL", score, 10.0)],
        }
        return {"me": side("1", 26.5), "opponent": side("2", 3.0)}

    def test_board_with_per_league_error_and_no_manual_league(self):
        with patch("ffassistant.api.scoreboard._fetch_live_matchup", side_effect=self._fake_fetch), patch(
            "ffassistant.connectors.espn.get_nfl_scoreboard", return_value=NFL
        ):
            resp = self.client.get("/api/scoreboard?season=2026&week=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        by_name = {m["league_name"]: m for m in data["matchups"]}
        self.assertNotIn("Manual League", by_name)
        self.assertEqual(by_name["Broken League"]["error"], "cookie expired")

        ok = by_name["Test League"]
        self.assertIsNone(ok["error"])
        self.assertEqual(ok["me"]["score"], 26.5)
        self.assertEqual(ok["me"]["team_name"], self._team_name(1))
        self.assertEqual(ok["opponent"]["team_name"], self._team_name(2))
        self.assertEqual(ok["me"]["live_projected"], 26.5)  # DAL game final

    def test_week_required(self):
        self.assertEqual(self.client.get("/api/scoreboard?season=2026").status_code, 400)

    def _team_name(self, team_id):
        conn = sqlite3.connect(self.db_path)
        name = conn.execute("SELECT team_name FROM teams WHERE team_id = ?", (team_id,)).fetchone()[0]
        conn.close()
        return name
