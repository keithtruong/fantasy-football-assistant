"""CLI entry point for filling in a week's W-L matchups rows from whatever
the platform connectors have already synced (see ffassistant.wl for the
actual work) — the "in-season automation candidate" CLAUDE.md flags for
PF/PA entry, instead of Keith typing each league's result in by hand.

Runs a rosters-only refresh first (see ffassistant.refresh) so the numbers
it reads are current, then autofills. A league whose week isn't final yet on
its platform (or has no traditional W-L, e.g. a Guillotine-style league) is
skipped, not guessed at — safe to just rerun later once it catches up.

Usage:
    python -m scripts.autofill_wl [--week 1] [--season 2026]

--season defaults to the current year. --week defaults to "last week" --
smart_current_week() minus one, since that live lookup reports the week
currently being played, not the one that just finished (confirmed by
inspection: it had already advanced by Tuesday morning, the same day this is
meant to run unattended) -- pass --week explicitly to fill in a specific past
week instead.
"""

import argparse
import datetime
import sys

from ffassistant.db import get_connection
from ffassistant.guillotine import sync_and_fill_week
from ffassistant.refresh import LOG_PATH, run_rosters_only_refresh
from ffassistant.season import FIRST_WEEK, smart_current_week
from ffassistant.wl import autofill_from_platform_sync, sync_league_season_record

_STATUS_LABELS = {
    "not_final_yet": "not final yet on the platform",
    "no_traditional_record": "no traditional W-L record (e.g. a Guillotine-style league)",
    "no_my_team_flagged": "no team flagged is_mine",
    "no_platform_match": "no matching platform league this season",
    "unsupported_platform": "Guillotine autofill only supports Yahoo today",
    "not_enough_history": "not enough snapshot history yet to resolve this week's result",
}


def _resolve_week(conn, season: int, explicit_week: int | None) -> int | None:
    """--week if given; otherwise last week, derived from smart_current_week()
    minus one. Returns None if there's nothing resolvable (no live data and
    no week1_start_date fallback, or the season hasn't reached week 2 yet --
    week 1 has no "last week" to autofill)."""
    if explicit_week is not None:
        return explicit_week

    current = smart_current_week(conn, season)
    if current is None or current <= FIRST_WEEK:
        return None
    return current - 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    args = parser.parse_args(argv)
    season = args.season if args.season is not None else datetime.date.today().year

    conn = get_connection()
    week = _resolve_week(conn, season, args.week)
    if week is None:
        print("Could not resolve a week to autofill (no live current-week data yet, or nothing finished "
              "before week 1) -- pass --week explicitly.")
        return 1

    run_rosters_only_refresh(conn, season=season, week=week, log=False)
    results = autofill_from_platform_sync(conn, season, week)
    guillotine_results = sync_and_fill_week(conn, season, week)

    lines = [f"=== {datetime.datetime.now().isoformat(timespec='seconds')} — W-L autofill season={season} week={week} ==="]
    filled = [r for r in results if r["status"] == "filled"]
    lines.append(f"Filled: {len(filled)}/{len(results)} leagues")
    for r in results:
        if r["status"] == "filled":
            lines.append(f"  {r['league_history_name']}: {r['outcome']} {r['points_for']}-{r['points_against']}")
        else:
            lines.append(f"  {r['league_history_name']}: SKIPPED — {_STATUS_LABELS.get(r['status'], r['status'])}")

    guillotine_filled = [r for r in guillotine_results if r["status"] == "filled"]
    if guillotine_results:
        lines.append(f"Guillotine filled: {len(guillotine_filled)}/{len(guillotine_results)} leagues")
        for r in guillotine_results:
            if r["status"] == "filled":
                lines.append(f"  {r['league_history_name']}: {r['rank']} of {r['remaining_count']} — {r['points_for']} pts")
            else:
                lines.append(f"  {r['league_history_name']}: SKIPPED — {_STATUS_LABELS.get(r['status'], r['status'])}")

    # Keeps the Leagues tab's W/L/T current every week, same way matchups
    # already gets refreshed above — league_seasons is a separate table
    # (buy-in/payout/finish live there too), not derived at read time.
    history_rows = conn.execute("SELECT league_history_id, name FROM league_history WHERE active = 1").fetchall()
    for history in history_rows:
        sync_league_season_record(conn, history["league_history_id"], season)
    lines.append(f"Synced league_seasons W/L/T for {len(history_rows)} leagues")

    output = "\n".join(lines)
    print(output)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(output + "\n\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
