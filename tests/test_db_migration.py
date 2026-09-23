import sqlite3
import tempfile
import unittest
from pathlib import Path

from ffassistant.db import get_connection, init_db

# The pre-'manual' leagues table shape, as it existed in schema.sql before this
# migration was added — used to prove init_db() upgrades a real pre-existing
# database in place, not just a fresh one already carrying the new schema.
_OLD_LEAGUES_SCHEMA = """
CREATE TABLE leagues (
    league_id           INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    platform            TEXT NOT NULL CHECK (platform IN ('espn', 'yahoo', 'sleeper')),
    platform_league_id  TEXT,
    team_count          INTEGER NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes               TEXT
);
CREATE TABLE teams (
    team_id             INTEGER PRIMARY KEY,
    league_id           INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    platform_team_id    TEXT,
    team_name           TEXT NOT NULL,
    display_name        TEXT,
    is_mine             INTEGER NOT NULL DEFAULT 0 CHECK (is_mine IN (0, 1)),
    draft_position      INTEGER,
    UNIQUE (league_id, platform_team_id)
);
"""


class LeaguesPlatformMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "old.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _seed_old_schema(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(_OLD_LEAGUES_SCHEMA)
        conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) "
            "VALUES (1, 'Old League', 'espn', 2, 1)"
        )
        conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine, draft_position) "
            "VALUES (1, 1, 'Team A', 1, 1)"
        )
        conn.commit()
        conn.close()

    def test_rejects_manual_platform_before_migration(self):
        self._seed_old_schema()
        conn = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO leagues (name, platform, team_count) VALUES ('Placeholder', 'manual', 0)"
            )
        conn.close()

    def test_init_db_upgrades_existing_database_in_place(self):
        self._seed_old_schema()
        init_db(self.db_path)

        conn = get_connection(self.db_path)
        # Old row survived the table rebuild with its original league_id/data intact.
        league = conn.execute("SELECT * FROM leagues WHERE league_id = 1").fetchone()
        self.assertEqual(league["name"], "Old League")
        self.assertEqual(league["platform"], "espn")

        # The FK reference from the pre-existing teams row still resolves.
        team = conn.execute("SELECT * FROM teams WHERE team_id = 1").fetchone()
        self.assertEqual(team["league_id"], 1)
        self.assertEqual(team["team_name"], "Team A")

        # The new CHECK constraint now accepts 'manual'.
        conn.execute("INSERT INTO leagues (name, platform, team_count) VALUES ('Placeholder', 'manual', 0)")
        conn.commit()
        manual = conn.execute("SELECT * FROM leagues WHERE platform = 'manual'").fetchone()
        self.assertEqual(manual["name"], "Placeholder")
        conn.close()

    def test_init_db_adds_waiver_priority_column(self):
        self._seed_old_schema()
        init_db(self.db_path)

        conn = get_connection(self.db_path)
        # Pre-existing team row survived, and the new column is present (NULL
        # until the next resync populates it).
        team = conn.execute("SELECT * FROM teams WHERE team_id = 1").fetchone()
        self.assertEqual(team["team_name"], "Team A")
        self.assertIsNone(team["waiver_priority"])

        conn.execute("UPDATE teams SET waiver_priority = 3 WHERE team_id = 1")
        conn.commit()
        self.assertEqual(
            conn.execute("SELECT waiver_priority FROM teams WHERE team_id = 1").fetchone()["waiver_priority"], 3
        )
        conn.close()

    def test_init_db_adds_standings_metadata_columns(self):
        self._seed_old_schema()
        init_db(self.db_path)

        conn = get_connection(self.db_path)
        # Pre-existing team row survived, and the new columns are present
        # (NULL until the next resync populates them).
        team = conn.execute("SELECT * FROM teams WHERE team_id = 1").fetchone()
        self.assertEqual(team["team_name"], "Team A")
        self.assertIsNone(team["points_for"])
        self.assertIsNone(team["points_against"])
        self.assertIsNone(team["playoff_pct"])
        self.assertIsNone(team["standing"])

        conn.execute(
            "UPDATE teams SET points_for = 950.5, points_against = 800.0, playoff_pct = 92.0, standing = 1 "
            "WHERE team_id = 1"
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM teams WHERE team_id = 1").fetchone()
        self.assertEqual(updated["playoff_pct"], 92.0)
        self.assertEqual(updated["standing"], 1)
        conn.close()

    def test_init_db_adds_game_date_and_projected_points_columns(self):
        self._seed_old_schema()
        conn = sqlite3.connect(self.db_path)
        # weekly_box_scores' pre-this-feature shape (no game_date/projected_points).
        conn.executescript(
            """
            CREATE TABLE players (player_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, position TEXT NOT NULL);
            CREATE TABLE weekly_box_scores (
                box_score_id INTEGER PRIMARY KEY,
                league_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                slot_name TEXT NOT NULL,
                points REAL NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute("INSERT INTO players (player_id, full_name, position) VALUES (1, 'Old Player', 'RB')")
        conn.execute(
            "INSERT INTO weekly_box_scores (league_id, season, week, team_id, player_id, slot_name, points) "
            "VALUES (1, 2025, 1, 1, 1, 'RB', 10.0)"
        )
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM weekly_box_scores WHERE box_score_id = 1").fetchone()
        self.assertEqual(row["points"], 10.0)  # pre-existing row survived
        self.assertIsNone(row["game_date"])  # new column present, NULL until a resync populates it
        self.assertIsNone(row["projected_points"])

        conn.execute("UPDATE weekly_box_scores SET game_date = '2025-09-07T13:00:00', projected_points = 12.5 WHERE box_score_id = 1")
        conn.commit()
        updated = conn.execute("SELECT * FROM weekly_box_scores WHERE box_score_id = 1").fetchone()
        self.assertEqual(updated["projected_points"], 12.5)
        conn.close()

    def test_init_db_adds_projected_points_to_free_agent_scores(self):
        self._seed_old_schema()
        conn = sqlite3.connect(self.db_path)
        # weekly_free_agent_scores' pre-this-feature shape (no projected_points).
        conn.executescript(
            """
            CREATE TABLE players (player_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, position TEXT NOT NULL);
            CREATE TABLE weekly_free_agent_scores (
                free_agent_score_id INTEGER PRIMARY KEY,
                league_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                points REAL NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute("INSERT INTO players (player_id, full_name, position) VALUES (1, 'Old Free Agent', 'RB')")
        conn.execute(
            "INSERT INTO weekly_free_agent_scores (league_id, season, week, player_id, points) "
            "VALUES (1, 2025, 1, 1, 9.0)"
        )
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM weekly_free_agent_scores WHERE free_agent_score_id = 1").fetchone()
        self.assertEqual(row["points"], 9.0)  # pre-existing row survived
        self.assertIsNone(row["projected_points"])  # new column present, NULL until a resync populates it

        conn.execute("UPDATE weekly_free_agent_scores SET projected_points = 4.0 WHERE free_agent_score_id = 1")
        conn.commit()
        updated = conn.execute("SELECT * FROM weekly_free_agent_scores WHERE free_agent_score_id = 1").fetchone()
        self.assertEqual(updated["projected_points"], 4.0)
        conn.close()

    def test_init_db_adds_roster_status_to_roster_spots(self):
        self._seed_old_schema()
        conn = sqlite3.connect(self.db_path)
        # roster_spots' pre-this-feature shape (no roster_status).
        conn.executescript(
            """
            CREATE TABLE players (player_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, position TEXT NOT NULL);
            CREATE TABLE roster_spots (
                roster_spot_id INTEGER PRIMARY KEY,
                team_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                acquired_via TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (team_id, player_id)
            );
            """
        )
        conn.execute("INSERT INTO players (player_id, full_name, position) VALUES (1, 'Old Rostered Guy', 'RB')")
        conn.execute("INSERT INTO roster_spots (roster_spot_id, team_id, player_id) VALUES (1, 1, 1)")
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM roster_spots WHERE roster_spot_id = 1").fetchone()
        self.assertIsNone(row["roster_status"])  # new column present, NULL until a resync populates it

        conn.execute("UPDATE roster_spots SET roster_status = 'starter' WHERE roster_spot_id = 1")
        conn.commit()
        updated = conn.execute("SELECT * FROM roster_spots WHERE roster_spot_id = 1").fetchone()
        self.assertEqual(updated["roster_status"], "starter")
        conn.close()

    def test_init_db_adds_points_to_weekly_matchups(self):
        self._seed_old_schema()
        conn = sqlite3.connect(self.db_path)
        # weekly_matchups' pre-this-feature shape (pairing only, no points).
        conn.executescript(
            """
            CREATE TABLE weekly_matchups (
                league_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                opponent_team_id INTEGER NOT NULL,
                PRIMARY KEY (league_id, season, week, team_id)
            );
            """
        )
        conn.execute(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (1, 2025, 1, 1, 2)"
        )
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM weekly_matchups WHERE team_id = 1").fetchone()
        self.assertEqual(row["opponent_team_id"], 2)  # pre-existing row survived
        self.assertIsNone(row["points_for"])  # new column present, NULL until a resync populates it
        self.assertIsNone(row["points_against"])

        conn.execute("UPDATE weekly_matchups SET points_for = 104.38, points_against = 84.26 WHERE team_id = 1")
        conn.commit()
        updated = conn.execute("SELECT * FROM weekly_matchups WHERE team_id = 1").fetchone()
        self.assertEqual(updated["points_for"], 104.38)
        conn.close()

    def test_init_db_is_idempotent(self):
        self._seed_old_schema()
        init_db(self.db_path)
        init_db(self.db_path)  # second run should be a no-op, not an error

        conn = get_connection(self.db_path)
        count = conn.execute("SELECT COUNT(*) AS c FROM leagues").fetchone()["c"]
        self.assertEqual(count, 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
