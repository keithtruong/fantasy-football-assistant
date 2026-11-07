"""Health rules for the ops watchdog: given the run log's status snapshot and
the news-pipeline files, what's broken right now?

Pure and clock-injected (no network, no Claude), so a cloud scheduled task can
run it cheaply through scripts/ops_check.py, and the rules are unit-tested.
Each problem has a stable key so the watchdog can alert once when a problem
appears and once when it clears, not on every check while it persists.

All time-of-day rules use Central time explicitly: this may run from a shell
whose own clock is UTC.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")

NEWS_WATCH_MAX_AGE = timedelta(minutes=45)  # polls at least every ~25 min from 7am
NEWS_WATCH_CHECK_FROM = time(8, 0)          # give the 7am restart an hour of grace
REFRESH_MAX_AGE = timedelta(days=7)   # weekly Tue/Wed schedule leaves a ~6-day gap
RECAP_PREP_DUE = time(9, 0)                 # Tuesday task runs 8:15
DIGESTS_MAX_LAG = timedelta(hours=30)       # digest task should follow a new request within a day
NEWS_EXTRACT_MAX_AGE = timedelta(days=3)


@dataclass(frozen=True)
class Problem:
    key: str
    message: str


def _parse(ts: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(ts).astimezone(CENTRAL) if ts else None


def _ago(now: datetime, then: datetime) -> str:
    mins = int((now - then).total_seconds() // 60)
    if mins < 90:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def find_problems(
    jobs: dict,
    now: datetime,
    digest_request_mtime: Optional[datetime] = None,
    digests_mtime: Optional[datetime] = None,
    request_player_count: int = 0,
    digest_count: int = 0,
    news_extract_mtime: Optional[datetime] = None,
) -> list[Problem]:
    now = now.astimezone(CENTRAL)
    problems: list[Problem] = []

    # Real-time news watcher (desktop, every 5 min)
    nw = jobs.get("news_watch", {})
    if nw.get("status") == "error":
        problems.append(Problem("news_watch_error", f"News watcher is failing: {nw.get('error')}"))
    if now.time() >= NEWS_WATCH_CHECK_FROM:
        last_ok = _parse(nw.get("last_ok_at"))
        if last_ok is None or now - last_ok > NEWS_WATCH_MAX_AGE:
            when = _ago(now, last_ok) if last_ok else "never"
            problems.append(Problem("news_watch_stale",
                                    f"News watcher hasn't polled successfully since {when}. Player news alerts are paused."))

    # Tuesday recap prep (desktop, 8:15 Tue)
    if now.weekday() == 1 and now.time() >= RECAP_PREP_DUE:
        # Accept the pre-2026-10-13 job name too (the Tuesday task ran as
        # "week_results_sync" before scripts/weekly_recap_prep.py took it over).
        candidates = [jobs[k] for k in ("recap_prep", "week_results_sync") if k in jobs]
        rp = max(candidates, key=lambda j: j.get("finished_at") or "", default={})
        finished = _parse(rp.get("finished_at"))
        if finished is None or finished.date() != now.date():
            problems.append(Problem("recap_prep_missing",
                                    "Tuesday results sync / recap prep hasn't run today. The TAMS recap is waiting on it."))
        elif rp.get("status") == "error":
            problems.append(Problem("recap_prep_error", f"Tuesday results sync / recap prep failed: {rp.get('error')}"))

    # Full in-season refresh (desktop) - only once it has ever reported a heartbeat
    ir = jobs.get("in_season_refresh")
    if ir:
        if ir.get("status") == "error":
            problems.append(Problem("in_season_refresh_error", f"In-season refresh is failing: {ir.get('error')}"))
        last_ok = _parse(ir.get("last_ok_at"))
        if last_ok is None or now - last_ok > REFRESH_MAX_AGE:
            when = _ago(now, last_ok) if last_ok else "never"
            problems.append(Problem("in_season_refresh_stale", f"In-season refresh hasn't succeeded since {when}."))

    # Player-news digests (cloud tasks reading a request the desktop writes)
    if digest_request_mtime and (digests_mtime is None or digest_request_mtime - digests_mtime > DIGESTS_MAX_LAG):
        problems.append(Problem("digests_stale",
                                "Player news digests are more than a day behind the latest roster news request. "
                                "The digest scheduled tasks may not be running."))
    elif (digest_request_mtime and digests_mtime and digests_mtime >= digest_request_mtime
          and request_player_count > 0 and digest_count == 0):
        problems.append(Problem("digests_empty",
                                f"The last digest run wrote 0 digests for {request_player_count} players with news."))

    if news_extract_mtime and now - news_extract_mtime.astimezone(CENTRAL) > NEWS_EXTRACT_MAX_AGE:
        problems.append(Problem("news_extract_stale",
                                f"Rotoworld headline extraction hasn't updated since {_ago(now, news_extract_mtime.astimezone(CENTRAL))}."))
    return problems


def diff(open_problems: dict, current: list[Problem]) -> tuple[list[Problem], list[str]]:
    """(newly opened problems, keys that cleared) relative to the last check."""
    current_keys = {p.key for p in current}
    new = [p for p in current if p.key not in open_problems]
    cleared = [k for k in open_problems if k not in current_keys]
    return new, cleared
