"""One-time (or rerun-anytime) backfill of a league's ENTIRE regular-season
matchup schedule — every week's opponent pairings, not just the current one.

Why this exists: ESPN publishes the full regular-season schedule up front,
before a single game is played, so there's no reason a future week's
pairings should be unknown just because that week hasn't "arrived" yet. The
regular in-season refresh (ffassistant.ingest.espn._sync_teams_and_rosters)
now also syncs next week's pairings proactively on every run, which keeps
things from drifting out of sync going forward — but that only ever reaches
one week ahead. This script closes the rest of the gap in one shot: run it
once and every remaining week of the season has its pairings ready for the
recap's Next Week Preview, no matter how many weeks out.

Usage:
    python -m scripts.sync_season_schedule --league-id 3 [--season 2026] [--through-week 17]

Safe to rerun anytime (full-replace per (league, season, week), same
convention as sync_weekly_matchups/sync_box_scores) — a week whose pairing
hasn't changed just gets overwritten with the same data. A week ESPN hasn't
published yet (extremely early in the offseason) or that errors for any
other reason is logged and skipped rather than aborting the whole run, so a
bad week doesn't block the rest of the schedule from syncing.
"""

import argparse
import datetime
import sys

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection
from ffassistant.ingest.espn import sync_weekly_matchups
from ffassistant.season import FIRST_WEEK, LAST_WEEK

# Same file ffassistant.refresh's scheduled jobs (and sync_week_results.py)
# log to — see sync_week_results.py's own comment for why this is a bare
# path constant rather than an import from ffassistant.refresh.
LOG_PATH = REPO_ROOT / "data" / "refresh_log.txt"


def _log(line: str) -> None:
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=None, help="Defaults to the current calendar year")
    parser.add_argument(
        "--through-week",
        type=int,
        default=LAST_WEEK,
        help=f"Last week to sync, inclusive (default: {LAST_WEEK}, the last week of the regular season)",
    )
    args = parser.parse_args(argv)

    conn = get_connection()
    season = args.season or datetime.date.today().year

    league = conn.execute(
        "SELECT platform_league_id FROM leagues WHERE league_id = ? AND platform = 'espn'", (args.league_id,)
    ).fetchone()
    if league is None or not league["platform_league_id"]:
        _log(f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — sync_season_schedule league_id={args.league_id} season={season} ===")
        _log(f"  FAILED — no ESPN league found for league_id={args.league_id}")
        _log("")
        return 1
    espn_league_id = int(league["platform_league_id"])

    header = (
        f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — sync_season_schedule "
        f"league_id={args.league_id} season={season} weeks={FIRST_WEEK}-{args.through_week} ==="
    )
    _log(header)

    total_written = 0
    failures = []
    for week in range(FIRST_WEEK, args.through_week + 1):
        try:
            written = sync_weekly_matchups(conn, args.league_id, espn_league_id, season, week)
            _log(f"  Week {week}: {written} pairing rows written")
            total_written += written
        except Exception as e:
            _log(f"  Week {week}: FAILED — {e}")
            failures.append(week)

    _log(f"  Total: {total_written} rows written across {args.through_week - FIRST_WEEK + 1} weeks")
    if failures:
        _log(f"  Weeks that failed: {failures}")
    _log("")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
