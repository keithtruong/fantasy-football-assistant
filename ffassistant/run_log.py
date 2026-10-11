"""Heartbeat log for every scheduled/background job in this project.

Every job (the in-season refresh, the news watcher, week-result syncs, ...)
reports one record per run here: job name, start/finish time, status, how many
items it processed, and any error. Two files, both under data/ and gitignored:

- data/run_log.jsonl — append-only history, one JSON object per line, trimmed
  to the most recent MAX_LOG_LINES so it never grows unbounded.
- data/ops_status.json — the latest record per job, rewritten atomically
  (temp file + os.replace) after every run. This is the one file anything
  outside this codebase reads — the cloud watchdog and the status page —
  so it never has to open the SQLite database (see CLAUDE.md's network-mount
  locking note for why that matters).

Deliberately file-based rather than a SQLite table: the reader is a separate
process on a separate machine, and a small JSON snapshot is safe to copy at
any moment, mid-write or not.

"Status" is what the job itself concluded, not just "it ran": a job that ran
fine but found nothing to do should say so via `items` (e.g. 0) and `note`,
so the watchdog can tell "ran, nothing new" apart from "ran, silently broken"
(the gap that made a 5-second "succeeded" scheduled run uninformative).
"""

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ffassistant.config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"
RUN_LOG_PATH = DATA_DIR / "run_log.jsonl"
STATUS_PATH = DATA_DIR / "ops_status.json"
MAX_LOG_LINES = 5000

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"  # ran, but deliberately did nothing (e.g. outside its polling window)
STATUS_ERROR = "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_run(
    job: str,
    status: str,
    started_at: str,
    finished_at: Optional[str] = None,
    items: Optional[int] = None,
    note: Optional[str] = None,
    error: Optional[str] = None,
    log_path: Optional[Path] = None,
    status_path: Optional[Path] = None,
) -> dict:
    """Append one run record to the log and update that job's entry in the
    status snapshot. Returns the record written. Paths default to the module
    constants, resolved at call time so tests can patch them."""
    log_path = log_path or RUN_LOG_PATH
    status_path = status_path or STATUS_PATH
    record = {
        "job": job,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at or _now(),
        "items": items,
        "note": note,
        "error": error,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    _trim(log_path)
    _update_status(record, status_path)
    return record


def read_status(status_path: Optional[Path] = None) -> dict:
    """{job_name: latest record}. Empty dict if nothing has run yet."""
    status_path = status_path or STATUS_PATH
    if not status_path.exists():
        return {}
    return json.loads(status_path.read_text(encoding="utf-8")).get("jobs", {})


def run_logged(job: str, fn: Callable, *args, **kwargs) -> int:
    """Run a CLI-style `fn` and record the outcome; returns the exit code.

    `fn` may return an int exit code, or an (exit_code, details) tuple where
    details may carry "items" and "note" (and "status", to report "skipped").
    An uncaught exception is recorded as an error and then re-raised, so the
    scheduler still sees the failure too.

    Used at each script's `if __name__ == "__main__"` entry point rather than
    inside main() itself, so unit tests that call main() directly never write
    to the real data/ files.
    """
    started_at = _now()
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        record_run(job, STATUS_ERROR, started_at, error=f"{type(e).__name__}: {e}",
                   note=traceback.format_exc(limit=3)[-500:])
        raise
    code, details = (result if isinstance(result, tuple) else (result, {}))
    code = code or 0
    status = details.get("status") or (STATUS_OK if code == 0 else STATUS_ERROR)
    record_run(job, status, started_at, items=details.get("items"), note=details.get("note"),
               error=details.get("error") or (None if code == 0 else f"exit code {code}"))
    return code


def _update_status(record: dict, status_path: Path) -> None:
    jobs = read_status(status_path)
    previous = jobs.get(record["job"], {})
    entry = dict(record)
    # Keep the last *successful* run around separately: a job that's been
    # erroring or skipping for hours still needs "last real success" visible.
    if record["status"] == STATUS_OK:
        entry["last_ok_at"] = record["finished_at"]
    else:
        entry["last_ok_at"] = previous.get("last_ok_at")
    jobs[record["job"]] = entry
    payload = {"updated_at": record["finished_at"], "jobs": jobs}
    tmp = status_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, status_path)


def _trim(log_path: Path) -> None:
    # Cheap size check first so the common case never reads the whole file.
    if log_path.stat().st_size < MAX_LOG_LINES * 120:
        return
    lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) > MAX_LOG_LINES:
        log_path.write_text("".join(lines[-MAX_LOG_LINES:]), encoding="utf-8")
