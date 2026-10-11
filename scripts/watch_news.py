"""CLI entry point for the real-time Rotoworld watcher — see
ffassistant.news_watch for what a poll does and ffassistant.run_log for the
heartbeat every run leaves behind.

Registered as a Windows scheduled task firing every 5 minutes (see
scripts/register_news_watch_task.bat); the script itself decides whether this
particular firing should actually poll (pre-slate windows: every time;
otherwise every ~25 minutes; overnight: never), so the schedule lives in one
place in code instead of a pile of Task Scheduler triggers.

Usage:
    python -m scripts.watch_news           # respects the polling windows
    python -m scripts.watch_news --force   # poll right now regardless
"""

import argparse
import sys
from datetime import datetime

from ffassistant import run_log
from ffassistant.db import get_connection
from ffassistant.news_watch import poll, should_poll

JOB_NAME = "news_watch"


def main(argv=None, status=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Poll now, ignoring the polling windows")
    args = parser.parse_args(argv)

    if not args.force:
        job_status = (status if status is not None else run_log.read_status()).get(JOB_NAME, {})
        last_ok = job_status.get("last_ok_at")
        last_ok_at = datetime.fromisoformat(last_ok).astimezone() if last_ok else None
        go, reason = should_poll(datetime.now().astimezone(), last_ok_at)
        if not go:
            return 0, {"status": run_log.STATUS_SKIPPED, "note": reason}

    conn = get_connection()
    try:
        summary = poll(conn)
    finally:
        conn.close()

    if summary["seeded"]:
        note = f"first run: seeded {summary['new_items']} existing items, no alerts sent"
    else:
        note = (f"{summary['new_items']} new across {summary['pages']} page(s); "
                f"{summary['matched']} about your players, {summary['urgent']} urgent")
    if summary.get("send_errors"):
        error = f"{summary['send_errors']} alert(s) failed to send — see data/alerts.jsonl"
        print(f"{note}; {error}")
        return 1, {"items": summary["new_items"], "note": note, "error": error}
    print(note)
    return 0, {"items": summary["new_items"], "note": note}


if __name__ == "__main__":
    sys.exit(run_log.run_logged(JOB_NAME, main))
