"""Single seam for anything this project wants to push to Keith.

Every alert is always appended to data/alerts.jsonl (the local record the
status page can read), and then — when GROUPME_ALERTS_BOT_ID is configured —
pushed to Keith's phone via a GroupMe bot in a private group with only him in
it. Callers (the news watcher, later the rankings/add-drop checks) only ever
call send(); the channel lives here.

Safety: the GroupMe connector falls back to GROUPME_BOT_ID (the TAMS league
group) when given no bot id, so this module never calls it without an explicit
alerts bot id, and refuses outright if the two are configured to the same bot.
A personal injury alert must never land in the league chat.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ffassistant import config
from ffassistant.config import REPO_ROOT
from ffassistant.connectors import groupme

ALERTS_PATH = REPO_ROOT / "data" / "alerts.jsonl"
GROUPME_MAX_CHARS = 1000


def format_message(alert: dict) -> str:
    if alert.get("kind") == "player_news":
        lines = [f"\U0001F6A8 {alert['player']}: {alert['headline']}"]
        starting = alert.get("starting_in") or []
        others = [l["league"] for l in alert.get("leagues", []) if l["league"] not in starting]
        if starting:
            lines.append("Starting in: " + ", ".join(starting))
        if others:
            lines.append("Also on: " + ", ".join(others))
        if alert.get("link"):
            lines.append(alert["link"])
        text = "\n".join(lines)
    else:
        text = alert.get("text") or json.dumps(alert)
    return text[:GROUPME_MAX_CHARS]


def send(alert: dict, alerts_path: Optional[Path] = None, bot_id: Optional[str] = None) -> dict:
    """Records the alert locally, then pushes it if a channel is configured.

    Returns the record, with "delivered" (True/False) and, on failure,
    "error". Never raises on a delivery failure — the caller reports it
    (the news watcher turns it into a failed run in the run log) so one bad
    push doesn't stop the remaining alerts from going out.
    """
    alerts_path = alerts_path or ALERTS_PATH
    bot_id = bot_id if bot_id is not None else config.GROUPME_ALERTS_BOT_ID
    record = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **alert,
              "delivered": False}

    if not bot_id:
        record["error"] = None  # no channel configured yet: log-only by design, not a failure
    elif bot_id == config.GROUPME_BOT_ID:
        record["error"] = "GROUPME_ALERTS_BOT_ID is the TAMS league bot; refusing to post alerts there"
    else:
        try:
            groupme.post_message(format_message(alert), bot_id=bot_id)
            record["delivered"] = True
        except Exception as e:
            record["error"] = f"{type(e).__name__}: {e}"

    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    with alerts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record
