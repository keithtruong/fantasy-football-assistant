"""One watchdog check: evaluate ffassistant.ops_check's rules against the
current run-log snapshot and news files, alert Keith (private GroupMe alerts
group, via ffassistant.notify) about problems that are NEW since the last
check, and send a "recovered" note for problems that cleared. Problems that
persist are not re-alerted. State lives in data/ops_watchdog_state.json.

Run by the cloud "FF Ops Watchdog" scheduled tasks through device_bash, so the
check itself costs no tokens; can also be run by hand.

Usage:
    python -m scripts.ops_check           # check, alert on changes, print a summary
    python -m scripts.ops_check --dry-run # check and print only; no alerts, no state change
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from ffassistant import notify, run_log
from ffassistant.config import PLAYER_DIGEST_REQUEST_PATH, PLAYER_DIGESTS_IMPORT_PATH, REPO_ROOT, ROTOWORLD_NEWS_IMPORT_PATH
from ffassistant.ops_check import CENTRAL, diff, find_problems

STATE_PATH = REPO_ROOT / "data" / "ops_watchdog_state.json"


def _mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.exists() else None


def _count(path, key):
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get(key, []))
    except (OSError, ValueError):
        return 0


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    now = now or datetime.now(CENTRAL)

    problems = find_problems(
        run_log.read_status(), now,
        digest_request_mtime=_mtime(PLAYER_DIGEST_REQUEST_PATH),
        digests_mtime=_mtime(PLAYER_DIGESTS_IMPORT_PATH),
        request_player_count=_count(PLAYER_DIGEST_REQUEST_PATH, "players"),
        digest_count=_count(PLAYER_DIGESTS_IMPORT_PATH, "digests"),
        news_extract_mtime=_mtime(ROTOWORLD_NEWS_IMPORT_PATH),
    )
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"open": {}}
    new, cleared = diff(state["open"], problems)

    stamp = now.strftime("%a %-I:%M%p") if sys.platform != "win32" else now.strftime("%a %#I:%M%p")
    if not args.dry_run:
        for p in new:
            notify.send({"kind": "ops", "text": f"⚠️ FF Assistant: {p.message}"})
        for key in cleared:
            notify.send({"kind": "ops", "text": f"✅ FF Assistant recovered: {state['open'][key]['message']}"})
        state["open"] = {p.key: state["open"].get(p.key, {"since": now.isoformat(timespec="minutes"), "message": p.message})
                         for p in problems}
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if not problems:
        print(f"[{stamp}] All clear." + (f" Recovered: {', '.join(cleared)}." if cleared else ""))
    else:
        print(f"[{stamp}] {len(problems)} problem(s), {len(new)} new" + (" (alerted)" if new and not args.dry_run else "") + ":")
        for p in problems:
            print(f"  - {p.message}")
        if cleared:
            print(f"  Recovered: {', '.join(cleared)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
