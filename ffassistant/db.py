"""SQLite connection helper and schema initialization."""

import sqlite3
from pathlib import Path

from ffassistant.config import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Column additions to tables that already existed before the column was
    introduced. `CREATE TABLE IF NOT EXISTS` in schema.sql only covers brand-new
    databases, so a real ALTER TABLE is needed here for the one shared db file.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)")}
    if "is_rookie" not in columns:
        conn.execute(
            "ALTER TABLE players ADD COLUMN is_rookie INTEGER NOT NULL DEFAULT 0 CHECK (is_rookie IN (0, 1))"
        )

    draft_picks_columns = {row["name"] for row in conn.execute("PRAGMA table_info(draft_picks)")}
    if "notes" not in draft_picks_columns:
        conn.execute("ALTER TABLE draft_picks ADD COLUMN notes TEXT")

    _migrate_leagues_platform_check(conn)


def _migrate_leagues_platform_check(conn: sqlite3.Connection) -> None:
    """Widens leagues.platform's CHECK constraint to also allow 'manual' (see
    schema.sql). SQLite has no ALTER TABLE support for changing a CHECK
    constraint, so this rebuilds the table when the old constraint is still in
    place — a no-op once migrated. league_id is an INTEGER PRIMARY KEY (a
    rowid alias), so copying rows with their existing league_id preserves
    every other table's foreign-key references to it.

    `PRAGMA foreign_keys = OFF` is required for the DROP TABLE step: with
    enforcement on, SQLite cascade-deletes every row in a child table (teams,
    draft_picks, etc. via their `ON DELETE CASCADE`) the instant its parent
    table is dropped — confirmed directly, not assumed. The pragma is also a
    no-op inside a pending transaction, hence the explicit commit before
    toggling it.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'leagues'").fetchone()
    if row is None or "'manual'" in row["sql"]:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        CREATE TABLE leagues_new (
            league_id           INTEGER PRIMARY KEY,
            name                TEXT NOT NULL,
            platform            TEXT NOT NULL CHECK (platform IN ('espn', 'yahoo', 'sleeper', 'manual')),
            platform_league_id  TEXT,
            team_count          INTEGER NOT NULL,
            active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            notes               TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO leagues_new (league_id, name, platform, platform_league_id, team_count, active, notes) "
        "SELECT league_id, name, platform, platform_league_id, team_count, active, notes FROM leagues"
    )
    conn.execute("DROP TABLE leagues")
    conn.execute("ALTER TABLE leagues_new RENAME TO leagues")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
