"""CLI entry point for the full in-season refresh — see ffassistant.refresh for
the actual work (shared with the in-season "Refresh All Leagues" button, see
ffassistant.api.refresh), so this is just argument parsing and an exit code.

Meant to be run both on a schedule (see the Task Scheduler entry set up
alongside this script) and by hand for an immediate on-demand refresh.

Usage:
    python -m scripts.refresh_in_season [--season 2026] [--week 3]

--season/--week default to the current year and ffassistant.season.smart_current_week()
respectively — which prefers a live NFL-week lookup over the manual
week1_start_date setting (see League Settings' Season panel), so no setup is
normally needed. If week resolution still comes back empty (live lookup
unreachable and week1_start_date unset) and --week isn't passed, the
roster/status sync still runs (just without player_status), and rankings
syncs are skipped with a warning, since weekly rankings specifically require
a week.
"""

import argparse
import sys

from ffassistant.db import get_connection
from ffassistant.refresh import run_full_refresh


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    args = parser.parse_args(argv)

    conn = get_connection()
    summary = run_full_refresh(conn, season=args.season, week=args.week)

    return 1 if summary["had_failure"] else 0


if __name__ == "__main__":
    sys.exit(main())
