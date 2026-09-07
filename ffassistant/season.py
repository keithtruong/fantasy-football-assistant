"""Current-NFL-week helper. smart_current_week() is the one production code
should call — it prefers a live, no-setup-needed lookup (Sleeper's public NFL
state endpoint) and only falls back to current_week()'s date math (driven by
the once-a-year week1_start_date setting in season_settings, see schema.sql)
if that live lookup is unavailable. Week 1 is treated as starting on
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


def smart_current_week(conn: sqlite3.Connection, season: int) -> Optional[int]:
    """The "just figure it out" version of current_week: prefers a live lookup
    (no manual week1_start_date setup needed) and falls back to current_week()'s
    date math if the live source is unavailable or doesn't apply to `season`.
    This is what every production call site should use — current_week() itself
    stays a pure, deterministic function for testing and as the fallback.
    """
    live = _fetch_live_week(season)
    if live is not None:
        return live
    return current_week(conn, season)


def _fetch_live_week(season: int) -> Optional[int]:
    """Best-effort live lookup via Sleeper's public NFL state endpoint — public,
    unauthenticated, and independent of which platforms Keith's leagues are
    actually on. Preseason maps to week 1 (Keith's own call: there's nothing
    meaningful to show before the season starts, so default to the first
    week rather than None). Returns None on any network hiccup, a season
    mismatch, or an unexpected response shape — the caller falls back to
    week1_start_date-based date math instead of raising.
    """
    try:
        from ffassistant.connectors.sleeper import get_nfl_state

        state = get_nfl_state()
    except Exception:
        return None

    if str(state.get("season")) != str(season):
        return None
    if state.get("season_type") == "pre":
        return FIRST_WEEK

    week = state.get("week")
    if not isinstance(week, int) or not (FIRST_WEEK <= week <= LAST_WEEK):
        return None
    return week
