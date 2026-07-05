"""Create (or recreate) the local SQLite database from schema.sql.

Usage:
    python -m scripts.init_db
"""

from ffassistant.config import DB_PATH
from ffassistant.db import init_db

if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
