"""Current-NFL-week helper, driven by the once-a-year week1_start_date setting
in season_settings (see schema.sql). Week 1 is treated as starting on
week1_start_date and running 7 days, same for every week after it.
"""

import datetime
import sqlite3
from typing import Optional

FIRST_WEEK = 1
LAST_WEEK = 17


def get_week1_start_date(conn: sqlite3.Connection, season: int) -> Optional[datetime.date]:
    row = conn.execute(
        "SELECT week1_start_date FROM season_settings WHERE season = ?", (season,)
    ).fetchone()
    if row is None:
        return None
    return datetime.date.fromisoformat(row["week1_start_date"])


def set_week1_start_date(conn: sqlite3.Connection, season: int, week1_start_date: datetime.date) -> None:
    conn.execute(
        "INSERT INTO season_settings (season, week1_start_date) VALUES (?, ?) "
        "ON CONFLICT (season) DO UPDATE SET week1_start_date = excluded.week1_start_date",
        (season, week1_start_date.isoformat()),
    )
    conn.commit()


def current_week(
    conn: sqlite3.Connection, season: int, today: Optional[datetime.date] = None
) -> Optional[int]:
    """The current NFL week for `season`, or None if week1_start_date isn't set
    yet, or today falls before week 1 or after week 17 (offseason/draft-day)."""
    week1_start = get_week1_start_date(conn, season)
    if week1_start is None:
        return None

    today = today or datetime.date.today()
    week = ((today - week1_start).days // 7) + 1
    if week < FIRST_WEEK or week > LAST_WEEK:
        return None
    return week
