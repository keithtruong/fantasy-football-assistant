"""The full in-season refresh: rosters + player status + record/matchup for
every active platform league, plus weekly rankings, rest-of-season rankings,
and player news. Meant to be run
both on a schedule (see the Task Scheduler entry set up alongside this
script) and by hand for an immediate on-demand refresh.

Failures in one piece (an expired rankings cookie, one league's platform
being briefly down) don't stop the rest — everything that can still run,
does, and every failure is reported at the end, in the log, and via the
non-zero exit code.

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
import datetime
import sys

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection
from ffassistant.ingest import sync_league_from_platform
from ffassistant.ingest.news import sync_player_news
from ffassistant.ingest.rankings import sync_ros_rankings, sync_weekly_rankings
from ffassistant.name_matching import list_unresolved
from ffassistant.season import smart_current_week

LOG_PATH = REPO_ROOT / "data" / "refresh_log.txt"

# Same four buckets the Draft tool's scoring-format dropdown offers — a
# scheduled refresh doesn't know in advance which formats this season's
# leagues need, so it covers all of them.
SCORING_FORMATS = ("full_ppr", "half_ppr", "non_ppr", "superflex")


def refresh_rosters(conn, season, week):
    leagues = conn.execute(
        "SELECT league_id, name, platform, platform_league_id FROM leagues "
        "WHERE active = 1 AND platform != 'manual'"
    ).fetchall()

    results = []
    for league in leagues:
        try:
            sync_league_from_platform(
                conn, league["league_id"], league["platform"], league["platform_league_id"], season, week=week
            )
            results.append((league["name"], True, None))
        except Exception as e:
            results.append((league["name"], False, str(e)))
    return results


def refresh_weekly(conn, season, week):
    try:
        sync_weekly_rankings(conn, season, week)
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'weekly' AND season = ? AND week = ?",
            (season, week),
        ).fetchone()["c"]
        return True, f"{count} players", None
    except Exception as e:
        return False, None, str(e)


def refresh_ros(conn, season):
    per_format = {}
    errors = []
    for scoring_format in SCORING_FORMATS:
        try:
            sync_ros_rankings(conn, season, scoring_format)
            per_format[scoring_format] = conn.execute(
                "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'ros' AND season = ? AND scoring_format = ?",
                (season, scoring_format),
            ).fetchone()["c"]
        except Exception as e:
            errors.append(f"{scoring_format}: {e}")
    return per_format, errors


def refresh_news(conn):
    try:
        sync_player_news(conn)
        count = conn.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"]
        return True, f"{count} headlines matched", None
    except Exception as e:
        return False, None, str(e)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=datetime.date.today().year)
    parser.add_argument("--week", type=int, default=None)
    args = parser.parse_args(argv)

    conn = get_connection()
    season = args.season
    week = args.week if args.week is not None else smart_current_week(conn, season)

    lines = [f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — season={season} week={week} ==="]
    had_failure = False

    roster_results = refresh_rosters(conn, season, week)
    ok_count = sum(1 for _, ok, _ in roster_results if ok)
    lines.append(f"Rosters/status: {ok_count}/{len(roster_results)} leagues synced")
    for name, ok, error in roster_results:
        if not ok:
            had_failure = True
            lines.append(f"  FAILED — {name}: {error}")

    if week is None:
        lines.append(
            "Weekly rankings: SKIPPED (no current week — live NFL-week lookup unreachable and no "
            "week1_start_date fallback set in League Settings; or pass --week)"
        )
    else:
        ok, detail, error = refresh_weekly(conn, season, week)
        if ok:
            lines.append(f"Weekly rankings (week {week}): {detail}")
        else:
            had_failure = True
            lines.append(f"Weekly rankings (week {week}): FAILED — {error}")

    ros_counts, ros_errors = refresh_ros(conn, season)
    if ros_counts:
        summary = ", ".join(f"{fmt}={count}" for fmt, count in ros_counts.items())
        lines.append(f"ROS rankings: {summary}")
    for error in ros_errors:
        had_failure = True
        lines.append(f"  ROS FAILED — {error}")

    ok, detail, error = refresh_news(conn)
    if ok:
        lines.append(f"Player news: {detail}")
    else:
        had_failure = True
        lines.append(f"Player news: FAILED — {error}")

    unresolved_count = len(list_unresolved(conn, "rankings_provider"))
    if unresolved_count:
        lines.append(f"{unresolved_count} rankings-provider names still unresolved — review in the app")

    output = "\n".join(lines)
    print(output)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(output + "\n\n")

    return 1 if had_failure else 0


if __name__ == "__main__":
    sys.exit(main())
