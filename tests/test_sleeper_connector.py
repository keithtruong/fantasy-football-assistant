import json
import unittest
from unittest.mock import patch

from ffassistant.connectors import sleeper


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestGetLeagueSettings(unittest.TestCase):
    @patch("ffassistant.connectors.sleeper.requests.get")
    def test_maps_roster_positions_and_scoring(self, mock_get):
        mock_get.return_value = FakeResponse(
            {
                "total_rosters": 10,
                "scoring_settings": {"rec": 1, "pass_td": 4},
                "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K", "BN", "BN", "BN"],
            }
        )
        settings = sleeper.get_league_settings("123")

        self.assertEqual(settings["team_count"], 10)
        self.assertEqual(settings["scoring"], {"rec": 1, "pass_td": 4})
        self.assertEqual(
            settings["roster_slots"],
            {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BENCH": 3},
        )


class TestGetTeams(unittest.TestCase):
    @patch("ffassistant.connectors.sleeper.requests.get")
    def test_combines_users_and_rosters(self, mock_get):
        users = [
            {"user_id": "u1", "display_name": "Keith", "metadata": {"team_name": "Keith's Team"}},
            {"user_id": "u2", "display_name": "Bob"},
        ]
        rosters = [
            {"roster_id": 1, "owner_id": "u1", "players": ["1234", "5678"], "settings": {"waiver_position": 3}},
            {"roster_id": 2, "owner_id": "u2", "players": ["9999"], "settings": {"waiver_position": 1}},
        ]
        mock_get.side_effect = lambda url, timeout: FakeResponse(users if url.endswith("/users") else rosters)

        teams = sleeper.get_teams("123")

        self.assertEqual(len(teams), 2)
        self.assertEqual(teams[0]["platform_team_id"], "1")
        self.assertEqual(teams[0]["team_name"], "Keith's Team")
        self.assertEqual(teams[0]["waiver_priority"], 3)
        self.assertEqual(teams[0]["player_ids"], ["1234", "5678"])
        # No team_name in metadata -> falls back to display_name.
        self.assertEqual(teams[1]["team_name"], "Bob")


class TestGetRosterPlayers(unittest.TestCase):
    def test_resolves_and_maps_defense_position(self):
        players_lookup = {
            "1234": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN"},
            "5678": {"first_name": "Kenneth", "last_name": "Walker", "position": "RB", "team": "SEA"},
            "SEA": {"full_name": "Seattle Seahawks", "position": "DEF", "team": "SEA"},
        }
        resolved = sleeper.get_roster_players(["1234", "5678", "SEA", "unknown_id"], players_lookup)

        self.assertEqual(len(resolved), 3)  # unknown_id silently skipped
        self.assertEqual(resolved[0]["full_name"], "Justin Jefferson")
        self.assertEqual(resolved[1]["full_name"], "Kenneth Walker")  # built from first/last
        self.assertEqual(resolved[2]["position"], "DST")  # mapped from Sleeper's 'DEF'

    def test_includes_injury_status(self):
        players_lookup = {
            "1234": {"full_name": "Banged Up Guy", "position": "RB", "team": "SEA", "injury_status": "Questionable"},
            "5678": {"full_name": "Healthy Guy", "position": "WR", "team": "MIN", "injury_status": None},
        }
        resolved = sleeper.get_roster_players(["1234", "5678"], players_lookup)
        self.assertEqual(resolved[0]["injury_status"], "Questionable")
        self.assertIsNone(resolved[1]["injury_status"])


class TestPlayersLookupCache(unittest.TestCase):
    @patch("ffassistant.connectors.sleeper.requests.get")
    def test_uses_cache_when_present(self, mock_get, tmp_path=None):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "sleeper_players.json"
            cache_path.write_text(json.dumps({"1": {"full_name": "Cached Player"}}))

            result = sleeper.get_players_lookup(cache_path=cache_path)

            mock_get.assert_not_called()
            self.assertEqual(result["1"]["full_name"], "Cached Player")

    @patch("ffassistant.connectors.sleeper.requests.get")
    def test_fetches_and_caches_when_absent(self, mock_get):
        import tempfile
        from pathlib import Path

        mock_get.return_value = FakeResponse({"1": {"full_name": "Fresh Player"}})
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "sleeper_players.json"

            result = sleeper.get_players_lookup(cache_path=cache_path)

            mock_get.assert_called_once()
            self.assertEqual(result["1"]["full_name"], "Fresh Player")
            self.assertTrue(cache_path.exists())


if __name__ == "__main__":
    unittest.main()
