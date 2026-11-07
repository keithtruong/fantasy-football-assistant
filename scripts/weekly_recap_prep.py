"""Tuesday-morning desktop half of the weekly recap pipeline: sync the week
that just wrapped, then build that same week's recap brief — so the cloud
half (a scheduled Claude task that writes the matchup narratives, renders,
and asks Keith to approve before anything reaches the league) always has
fresh, final data to work from.

Why one script instead of two scheduled ones: sync_week_results resolves its
default week as smart_current_week() - 1 (the week whose games are final),
while prepare_weekly_recap defaults to smart_current_week() (correct when run
by hand mid-week, wrong on a Tuesday). Resolving the week ONCE here and passing
it explicitly to both keeps them from ever disagreeing.

Writes a small stage file next to the brief —
data/recap_drafts/{league}_{season}_wk{week}_status.json — that the cloud task
reads and advances: brief_ready -> drafted (narratives written, page
rendered, preview sent to Keith) -> published (on the recap hub page and
posted to the league GroupMe, only after Keith approves). A rerun of this
script never moves a week backwards past "brief_ready" once it's drafted or
published, so re-syncing can't reopen a recap that's already gone out.

Usage:
    python -m scripts.weekly_recap_prep --league-id 3 [--season 2026] [--week 5]
"""

import argparse
import datetime
import json
import sys

from ffassistant import run_log
from ffassistant.db import get_connection
from scripts import prepare_weekly_recap, sync_week_results

JOB_NAME = "recap_prep"


def status_path(league_id: int, season: int, week: int):
    return prepare_weekly_recap.DRAFTS_DIR / f"{league_id}_{season}_wk{week}_status.json"


def write_stage(league_id: int, season: int, week: int, stage: str) -> dict:
    path = status_path(league_id, season, week)
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if current.get("stage") in ("drafted", "published") and stage == "brief_ready":
        return current  # never reopen a recap that's already drafted or out the door
    record = {**current, "league_id": league_id, "season": season, "week": week, "stage": stage,
              f"{stage}_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None,
                        help="Defaults to the week that just wrapped (smart_current_week() - 1)")
    args = parser.parse_args(argv)

    season = args.season or datetime.date.today().year
    conn = get_connection()
    try:
        week = sync_week_results._resolve_week(conn, season, args.week)
    finally:
        conn.close()
    if week is None:
        return 1, {"error": "could not resolve the week that just wrapped"}
    if week < sync_week_results.FIRST_WEEK:
        return 0, {"status": run_log.STATUS_SKIPPED, "note": f"week {week} is before the season starts"}

    common = ["--league-id", str(args.league_id), "--season", str(season), "--week", str(week)]
    if sync_week_results.main(common) != 0:
        return 1, {"error": f"week {week} results sync failed; brief not built"}
    if prepare_weekly_recap.main(common) != 0:
        return 1, {"error": f"week {week} synced, but building the recap brief failed"}

    brief_path, _ = prepare_weekly_recap._paths(args.league_id, season, week)
    matchups = len(json.loads(brief_path.read_text()))
    stage = write_stage(args.league_id, season, week, "brief_ready")["stage"]
    return 0, {"items": matchups, "note": f"week {week}: results synced, brief has {matchups} matchups (stage: {stage})"}


if __name__ == "__main__":
    sys.exit(run_log.run_logged(JOB_NAME, main))
