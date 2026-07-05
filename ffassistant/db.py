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
        conn.commit()
    finally:
        conn.close()
