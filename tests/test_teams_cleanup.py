import sqlite3
import unittest
from pathlib import Path

from ffassistant.ingest._teams import (
    refresh_nfl_team,
    remove_stale_teams,
    resolve_or_create_player,
    upsert_weekly_matchup,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestRemoveStaleTeams(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'espn', 2)"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (1, 1, 'old1', 'Old Team')"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (2, 1, 'cur1', 'Current Team')"
        )
        self.conn.commit()

    def test_removes_team_not_in_current_sync(self):
        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=["cur1"])
        remaining = {r["platform_team_id"] for r in self.conn.execute("SELECT * FROM teams WHERE league_id = 1")}
        self.assertEqual(remaining, {"cur1"})

    def test_keeps_stale_team_with_draft_picks(self):
        self.conn.execute(
            "INSERT INTO draft_picks (league_id, season, round, pick_number, team_id, player_id) "
            "VALUES (1, 2025, 1, 1, 1, NULL)"
        )
        self.conn.commit()

        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=["cur1"])

        remaining = {r["platform_team_id"] for r in self.conn.execute("SELECT * FROM teams WHERE league_id = 1")}
        self.assertEqual(remaining, {"old1", "cur1"})  # old1 kept — real draft data depends on it

    def test_no_current_teams_removes_everything_without_picks(self):
        remove_stale_teams(self.conn, league_id=1, current_platform_team_ids=[])
        remaining = self.conn.execute("SELECT * FROM teams WHERE league_id = 1").fetchall()
        self.assertEqual(remaining, [])


class TestRefreshNflTeam(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (1, 'A', 'RB', 'DEN')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (2, 'B', 'WR', NULL)"
        )
        self.conn.commit()

    def _team(self, player_id):
        return self.conn.execute(
            "SELECT nfl_team FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()["nfl_team"]

    def test_updates_when_team_changed(self):
        refresh_nfl_team(self.conn, 1, "DAL")
        self.assertEqual(self._team(1), "DAL")

    def test_fills_a_null_team(self):
        refresh_nfl_team(self.conn, 2, "KC")
        self.assertEqual(self._team(2), "KC")

    def test_none_does_not_blank_a_known_team(self):
        refresh_nfl_team(self.conn, 1, None)
        self.assertEqual(self._team(1), "DEN")


class TestResolveOrCreatePlayer(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def test_matches_existing_person_by_name(self):
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Josh Allen', 'QB')"
        )
        self.conn.commit()

        player_id = resolve_or_create_player(
            self.conn, "espn", {"full_name": "Josh Allen", "position": "QB", "nfl_team": "BUF"}
        )
        self.assertEqual(player_id, 1)

    def test_creates_new_person_on_genuine_miss(self):
        player_id = resolve_or_create_player(
            self.conn, "sleeper", {"full_name": "Some Rookie", "position": "WR", "nfl_team": "MIA"}
        )
        row = self.conn.execute("SELECT full_name, position FROM players WHERE player_id = ?", (player_id,)).fetchone()
        self.assertEqual((row["full_name"], row["position"]), ("Some Rookie", "WR"))

    def test_dst_matches_by_nfl_team_despite_different_naming_style(self):
        # Regression: Yahoo names defenses by bare nickname ("Cowboys") while
        # another source already created "DAL DST" — these must resolve to the
        # same canonical row instead of spawning a duplicate (see
        # scripts/dedupe_dst_players.py, which this sidesteps going forward).
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (304, 'DAL DST', 'DST', 'DAL')"
        )
        self.conn.commit()

        player_id = resolve_or_create_player(
            self.conn, "yahoo", {"full_name": "Cowboys", "position": "DST", "nfl_team": "Dal"}
        )
        self.assertEqual(player_id, 304)

        dst_count = self.conn.execute("SELECT COUNT(*) AS c FROM players WHERE position = 'DST'").fetchone()["c"]
        self.assertEqual(dst_count, 1)  # no duplicate row created

        alias = self.conn.execute(
            "SELECT player_id FROM player_aliases WHERE source = 'yahoo' AND alias_name = 'Cowboys'"
        ).fetchone()
        self.assertEqual(alias["player_id"], 304)  # future syncs resolve straight from the alias

    def test_dst_creates_new_row_when_no_existing_defense_for_that_team(self):
        player_id = resolve_or_create_player(
            self.conn, "yahoo", {"full_name": "Packers", "position": "DST", "nfl_team": "GB"}
        )
        row = self.conn.execute("SELECT full_name, nfl_team FROM players WHERE player_id = ?", (player_id,)).fetchone()
        self.assertEqual((row["full_name"], row["nfl_team"]), ("Packers", "GB"))


class TestUpsertWeeklyMatchup(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'L', 'yahoo', 2)"
        )
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name) VALUES (1, 1, 'A')")
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name) VALUES (2, 1, 'B')")
        self.conn.execute("INSERT INTO teams (team_id, league_id, team_name) VALUES (3, 1, 'C')")
        self.conn.commit()

    def test_inserts_new_matchup(self):
        upsert_weekly_matchup(self.conn, league_id=1, season=2026, week=1, team_id=1, opponent_team_id=2)
        row = self.conn.execute(
            "SELECT opponent_team_id FROM weekly_matchups WHERE league_id = 1 AND season = 2026 AND week = 1 AND team_id = 1"
        ).fetchone()
        self.assertEqual(row["opponent_team_id"], 2)

    def test_second_report_for_same_team_overwrites_instead_of_crashing(self):
        # Regression: a platform (seen on a guillotine/elimination-format Yahoo
        # league) can report the same team_id twice for one week — this used to
        # crash the whole roster sync on weekly_matchups' primary key.
        upsert_weekly_matchup(self.conn, league_id=1, season=2026, week=1, team_id=1, opponent_team_id=2)
        upsert_weekly_matchup(self.conn, league_id=1, season=2026, week=1, team_id=1, opponent_team_id=3)

        rows = self.conn.execute(
            "SELECT opponent_team_id FROM weekly_matchups WHERE league_id = 1 AND season = 2026 AND week = 1 AND team_id = 1"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opponent_team_id"], 3)


if __name__ == "__main__":
    unittest.main()
