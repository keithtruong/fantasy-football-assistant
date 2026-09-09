"""The full in-season refresh: rosters + player status + record/matchup for
every active platform league, plus weekly rankings, rest-of-season rankings,
and player news — for every league at once, not any one league in particular.

Shared by scripts/refresh_in_season.py (the scheduled desktop task) and the
in-season "Refresh All Leagues" button (see ffassistant.api.refresh) — both
trigger the exact same work and land in the same data/refresh_log.txt audit
trail, so it doesn't matter which one Keith (or the scheduler) used.

Failures in one piece (an expired rankings cookie, one league's platform
being briefly down) don't stop the rest — everything that can still run,
does, and every failure is reported in the returned summary and the log.
"""

import datetime

from ffassistant.config import REPO_ROOT
from ffassistant.ingest import sync_league_from_platform
from ffassistant.ingest.news import sync_player_news
from ffassistant.ingest.rankings import sync_ros_rankings, sync_weekly_rankings
from ffassistant.name_matching import list_unresolved
from ffassistant.season import smart_current_week

LOG_PATH = REPO_ROOT / "data" / "refresh_log.txt"

# Same four buckets the Draft tool's scoring-format dropdown offers — a
# whole-league-set refresh doesn't know in advance which formats this
# season's leagues need, so it covers all of them.
SCORING_FORMATS = ("full_ppr", "half_ppr", "non_ppr", "superflex")

# Weekly rankings have no superflex list at all (see
# ffassistant.connectors.rankings._SCORING_CODES) — only reception scoring
# varies, so this is SCORING_FORMATS minus "superflex".
WEEKLY_SCORING_FORMATS = ("full_ppr", "half_ppr", "non_ppr")


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
    per_format = {}
    errors = []
    for scoring_format in WEEKLY_SCORING_FORMATS:
        try:
            sync_weekly_rankings(conn, season, week, scoring_format)
            per_format[scoring_format] = conn.execute(
                "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'weekly' AND season = ? AND week = ? "
                "AND scoring_format = ?",
                (season, week, scoring_format),
            ).fetchone()["c"]
        except Exception as e:
            errors.append(f"{scoring_format}: {e}")
    return per_format, errors


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


def run_rosters_only_refresh(conn, season=None, week=None, log=True):
    """Rosters/status/record/matchup for every active league — the same first
    step as run_full_refresh, without weekly/ROS rankings or news. For a quick
    "did anyone make a move" check that doesn't need a rankings-provider hit
    (and isn't blocked by one, e.g. an expired cookie) — see
    ffassistant.api.refresh's /refresh_rosters, the "Refresh All Rosters" button.
    """
    season = season if season is not None else datetime.date.today().year
    if week is None:
        week = smart_current_week(conn, season)

    roster_results = refresh_rosters(conn, season, week)
    roster_failures = [{"league": name, "error": error} for name, ok, error in roster_results if not ok]
    summary = {
        "season": season,
        "week": week,
        "had_failure": bool(roster_failures),
        "rosters": {
            "synced": sum(1 for _, ok, _ in roster_results if ok),
            "total": len(roster_results),
            "failures": roster_failures,
        },
    }

    if log:
        lines = [
            f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — "
            f"season={season} week={week} (rosters only) ==="
        ]
        lines.append(f"Rosters/status: {summary['rosters']['synced']}/{summary['rosters']['total']} leagues synced")
        for failure in roster_failures:
            lines.append(f"  FAILED — {failure['league']}: {failure['error']}")
        output = "\n".join(lines)
        print(output)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(output + "\n\n")

    return summary


def run_full_refresh(conn, season=None, week=None, log=True):
    """Runs every piece of the in-season refresh and returns a summary dict.

    season/week default to the current year and ffassistant.season.smart_current_week()
    respectively, same as the CLI script — pass them explicitly to override
    (e.g. the API endpoint forwards whatever the client's in-season week
    input currently holds).
    """
    season = season if season is not None else datetime.date.today().year
    if week is None:
        week = smart_current_week(conn, season)

    summary = {"season": season, "week": week, "had_failure": False}

    roster_results = refresh_rosters(conn, season, week)
    roster_failures = [{"league": name, "error": error} for name, ok, error in roster_results if not ok]
    summary["rosters"] = {
        "synced": sum(1 for _, ok, _ in roster_results if ok),
        "total": len(roster_results),
        "failures": roster_failures,
    }
    if roster_failures:
        summary["had_failure"] = True

    if week is None:
        summary["weekly"] = {"skipped": True, "counts": {}, "errors": []}
    else:
        weekly_counts, weekly_errors = refresh_weekly(conn, season, week)
        summary["weekly"] = {"skipped": False, "counts": weekly_counts, "errors": weekly_errors}
        if weekly_errors:
            summary["had_failure"] = True

    ros_counts, ros_errors = refresh_ros(conn, season)
    summary["ros"] = {"counts": ros_counts, "errors": ros_errors}
    if ros_errors:
        summary["had_failure"] = True

    news_ok, news_detail, news_error = refresh_news(conn)
    summary["news"] = {"ok": news_ok, "detail": news_detail, "error": news_error}
    if not news_ok:
        summary["had_failure"] = True

    summary["unresolved_count"] = len(list_unresolved(conn, "rankings_provider"))

    if log:
        _write_log(summary)

    return summary


def _write_log(summary):
    lines = [
        f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — "
        f"season={summary['season']} week={summary['week']} ==="
    ]

    rosters = summary["rosters"]
    lines.append(f"Rosters/status: {rosters['synced']}/{rosters['total']} leagues synced")
    for failure in rosters["failures"]:
        lines.append(f"  FAILED — {failure['league']}: {failure['error']}")

    weekly = summary["weekly"]
    if weekly["skipped"]:
        lines.append(
            "Weekly rankings: SKIPPED (no current week — live NFL-week lookup unreachable and no "
            "week1_start_date fallback set in League Settings; or pass --week)"
        )
    else:
        if weekly["counts"]:
            counts_summary = ", ".join(f"{fmt}={count}" for fmt, count in weekly["counts"].items())
            lines.append(f"Weekly rankings (week {summary['week']}): {counts_summary}")
        for error in weekly["errors"]:
            lines.append(f"  Weekly FAILED — {error}")

    ros = summary["ros"]
    if ros["counts"]:
        counts_summary = ", ".join(f"{fmt}={count}" for fmt, count in ros["counts"].items())
        lines.append(f"ROS rankings: {counts_summary}")
    for error in ros["errors"]:
        lines.append(f"  ROS FAILED — {error}")

    news = summary["news"]
    if news["ok"]:
        lines.append(f"Player news: {news['detail']}")
    else:
        lines.append(f"Player news: FAILED — {news['error']}")

    if summary["unresolved_count"]:
        lines.append(f"{summary['unresolved_count']} rankings-provider names still unresolved — review in the app")

    output = "\n".join(lines)
    print(output)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(output + "\n\n")
