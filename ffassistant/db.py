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
