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
