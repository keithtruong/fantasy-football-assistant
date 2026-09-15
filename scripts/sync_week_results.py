"""Sync the most recently COMPLETED week's box scores and free-agent scores
for one league — the piece run_full_refresh/refresh_in_season deliberately
leaves out of the regular roster/status cadence (see
ffassistant.ingest.espn.sync_box_scores' docstring: a box score only means
something once that week's games are final).

Meant to be run unattended on a recurring schedule (see the Task Scheduler
entry set up alongside this script) so Matchup Stories/Waiver Wire Watch
data is ready without anyone triggering this by hand each week — as well as
by hand for an immediate on-demand sync.

Usage:
    python -m scripts.sync_week_results --league-id 3 [--season 2026] [--week 1]

--week is intentionally NOT "whatever week is live right now" — with no
--week passed, this resolves to smart_current_week() - 1, i.e. the week
that just wrapped, since that's the one whose box scores are actually worth
syncing (the live/current week's games aren't final yet, so syncing it would
just write incomplete/zero stats). That also means this needs no per-week
argument change: the same no-args invocation is correct every week of the
season, so it's safe to leave on an unattended, recurring schedule.

Full-replace per (league, season, week) — see sync_box_scores/
sync_free_agent_scores — so it's harmless to rerun (scheduled or by hand)
before a week is fully final; it just picks up whatever ESPN currently
reports and gets overwritten again next run once the real final numbers
land. Pass --week explicitly to backfill a specific past week on demand
(e.g. a week further back than "the one that just wrapped").
"""

import argparse
import datetime
import sys

from ffassistant.db import get_connection
from ffassistant.ingest.espn import sync_box_scores, sync_free_agent_scores
from ffassistant.season import FIRST_WEEK, smart_current_week


def _resolve_week(conn, season, explicit_week):
    if explicit_week is not None:
        return explicit_week
    current = smart_current_week(conn, season)
    if current is None:
        return None
    return current - 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=None, help="Defaults to the current calendar year")
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Defaults to smart_current_week() - 1 (the week that just wrapped) — pass this to sync a specific past week instead",
    )
    args = parser.parse_args(argv)

    conn = get_connection()
    season = args.season or datetime.date.today().year
    week = _resolve_week(conn, season, args.week)
    if week is None:
        print("Could not resolve the current week (pass --week explicitly) — nothing to sync yet.", file=sys.stderr)
        return 0
    if week < FIRST_WEEK:
        print(f"Week {week} is before the season starts (week {FIRST_WEEK}) — nothing to sync yet.")
        return 0

    league = conn.execute(
        "SELECT platform_league_id FROM leagues WHERE league_id = ? AND platform = 'espn'", (args.league_id,)
    ).fetchone()
    if league is None or not league["platform_league_id"]:
        print(f"No ESPN league found for league_id={args.league_id}", file=sys.stderr)
        return 1
    espn_league_id = int(league["platform_league_id"])

    print(f"Syncing league_id={args.league_id} (ESPN {espn_league_id}) season={season} week={week}...")

    n_box = sync_box_scores(conn, args.league_id, espn_league_id, season, week)
    print(f"Box scores: {n_box} player-week rows written")

    n_fa = sync_free_agent_scores(conn, args.league_id, espn_league_id, season, week)
    print(f"Free agents: {n_fa} rows written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
