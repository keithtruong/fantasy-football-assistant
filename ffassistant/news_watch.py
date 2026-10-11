"""Real-time Rotoworld watcher: "is there anything new since the last poll,
and is any of it about one of my players?"

Runs every 5 minutes as a native scheduled task (scripts/watch_news.py) and is
deliberately LLM-free end to end:

1. Change detection — fetch archive page 1 and diff its permalinks against
   news_seen. Nothing new = one HTTP request and done. If every item on a page
   is new, keep paging (up to MAX_PAGES) so a busy pre-kickoff burst isn't
   missed between polls.
2. Matching — the subject player's name leads each item's text; it's matched
   against Keith's own rostered players with the same `normalize()` the rest
   of the project uses (CLAUDE.md's deterministic name-matching rule).
3. Triage — the permalink slug is a slugified headline, so keyword phrases on
   it ("ruled out", "injured reserve", "traded", ...) decide urgent vs info.
   Only urgent items about Keith's players go to ffassistant.notify.

This is separate from, and doesn't replace, the full news sync in
ffassistant.ingest.news (Claude-extracted headlines/analysis + digests for the
In-season view). This only answers "what just broke," fast and cheaply.
"""

import sqlite3
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Optional

from ffassistant import notify
from ffassistant.connectors import nbc_news
from ffassistant.name_matching import normalize

MAX_PAGES = 5
RETENTION_DAYS = 14

# Phrases matched against the slug with hyphens turned into spaces and the
# whole thing padded with spaces, so " out " can't match inside "workout".
URGENT_PHRASES = (
    " out ", "ruled out", "will not play", "wont play", "not expected to play", "inactive",
    "doubtful", "injured reserve", " ir ", "pup list", "season ending", "out for season",
    "suspended", "suspension", "released", "waived", "cut by", "traded", " trade ",
    "carted", "torn", " acl", "achilles", "fracture", "surgery", "concussion protocol",
    "will start", "to start", " starts ", "named starter", "benched", "demoted", "lose starting",
    "status tbd", "game time decision", "gametime decision",
)

# Pre-slate windows (local time) where news moves lineups: every poll runs.
# Outside them polls thin out to every SLOW_INTERVAL; overnight they stop.
# weekday(): Mon=0 ... Thu=3 ... Sun=6.
FAST_WINDOWS = (
    (3, time(17, 0), time(20, 30)),   # Thursday night
    (6, time(8, 30), time(12, 15)),   # Sunday morning through early inactives
    (6, time(14, 0), time(15, 30)),   # Sunday late-window inactives
    (6, time(18, 0), time(19, 30)),   # Sunday night
    (0, time(17, 0), time(19, 30)),   # Monday night
)
SLOW_INTERVAL = timedelta(minutes=25)  # task fires every 5 min; 25 avoids drifting to 35
QUIET_BEFORE = time(7, 0)


def should_poll(now_local: datetime, last_ok_at: Optional[datetime]) -> tuple[bool, str]:
    """(poll?, reason). `now_local` and `last_ok_at` must be timezone-aware."""
    if now_local.time() < QUIET_BEFORE:
        return False, "overnight quiet hours"
    for weekday, start, end in FAST_WINDOWS:
        if now_local.weekday() == weekday and start <= now_local.time() <= end:
            return True, "pre-slate window"
    if last_ok_at is None or now_local - last_ok_at >= SLOW_INTERVAL:
        return True, "slow cadence due"
    return False, "slow cadence, polled recently"


def triage(slug: str) -> str:
    text = " " + slug.replace("-", " ").lower() + " "
    return "urgent" if any(phrase in text for phrase in URGENT_PHRASES) else "info"


def headline_from_slug(slug: str) -> str:
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS news_seen ("
        " link TEXT PRIMARY KEY, slug TEXT, lead_text TEXT,"
        " player_id INTEGER REFERENCES players (player_id) ON DELETE SET NULL,"
        " alert_level TEXT CHECK (alert_level IS NULL OR alert_level IN ('urgent', 'info')),"
        " first_seen_at TEXT NOT NULL)"
    )


def my_roster_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """normalized name -> {player_id, full_name, leagues: [{league, roster_status}]}
    for every player on one of Keith's own teams in an active league. DST rows
    are left out — team-defense news isn't keyed by a person's name."""
    rows = conn.execute(
        "SELECT p.player_id, p.full_name, l.name AS league_name, rs.roster_status "
        "FROM roster_spots rs "
        "JOIN teams t ON t.team_id = rs.team_id AND t.is_mine = 1 "
        "JOIN leagues l ON l.league_id = t.league_id AND l.active = 1 "
        "JOIN players p ON p.player_id = rs.player_id "
        "WHERE p.position IS NULL OR p.position != 'DST' "
        "ORDER BY l.name"
    ).fetchall()
    index: dict[str, dict] = {}
    for row in rows:
        key = normalize(row["full_name"])
        entry = index.setdefault(key, {"player_id": row["player_id"], "full_name": row["full_name"], "leagues": []})
        if entry["player_id"] != row["player_id"]:
            entry["ambiguous"] = True  # two different rostered players normalize the same — don't guess
        entry["leagues"].append({"league": row["league_name"], "roster_status": row["roster_status"]})
    return {k: v for k, v in index.items() if not v.get("ambiguous")}


def match_lead(lead_text: str, index: dict[str, dict]) -> Optional[dict]:
    """The rostered player whose normalized name the item's lead text starts
    with (longest name wins, so "Marvin Harrison" can't shadow a longer name)."""
    lead = normalize(lead_text)
    for name in sorted(index, key=len, reverse=True):
        if lead == name or lead.startswith(name + " "):
            return index[name]
    return None


def poll(
    conn: sqlite3.Connection,
    fetch_html: Callable[[int], str] = nbc_news.fetch_page_html,
    send: Callable[[dict], dict] = notify.send,
    now: Optional[datetime] = None,
) -> dict:
    """One poll. Returns a summary: pages fetched, new items, how many matched
    Keith's players, how many were urgent (and sent), and whether this was the
    first-ever run (which only seeds news_seen — no alerts for a backlog)."""
    ensure_table(conn)
    now = now or datetime.now(timezone.utc)
    seen = {row["link"] for row in conn.execute("SELECT link FROM news_seen")}
    seeding = not seen

    new_items: list[nbc_news.FeedItem] = []
    new_links: set[str] = set()
    pages = 0
    for page_num in range(1, MAX_PAGES + 1):
        page_items = nbc_news.extract_feed_items(fetch_html(page_num))
        pages += 1
        if not page_items:
            if page_num == 1:
                raise RuntimeError("no permalinked items found on page 1 — the page markup may have changed")
            break
        fresh = [i for i in page_items if i.link not in seen and i.link not in new_links]
        new_items.extend(fresh)
        new_links.update(i.link for i in fresh)
        if seeding or len(fresh) < len(page_items):
            break  # reached items we've already seen (or just seeding) — no need to page further

    index = {} if seeding else my_roster_index(conn)
    first_seen_at = now.isoformat(timespec="seconds")
    matched = urgent = send_errors = 0
    # Oldest first, so alerts go out in the order the news broke.
    for item in reversed(new_items):
        player = match_lead(item.lead_text, index) if index else None
        level = triage(item.slug) if player else None
        conn.execute(
            "INSERT OR IGNORE INTO news_seen (link, slug, lead_text, player_id, alert_level, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item.link, item.slug, item.lead_text, player["player_id"] if player else None, level, first_seen_at),
        )
        if not player:
            continue
        matched += 1
        if level == "urgent":
            urgent += 1
            result = send({
                "kind": "player_news",
                "level": level,
                "player_id": player["player_id"],
                "player": player["full_name"],
                "headline": headline_from_slug(item.slug),
                "link": item.link,
                "leagues": player["leagues"],
                "starting_in": [l["league"] for l in player["leagues"] if l["roster_status"] == "starter"],
            })
            if isinstance(result, dict) and result.get("error"):
                send_errors += 1

    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM news_seen WHERE first_seen_at < ?", (cutoff,))
    conn.commit()

    return {"pages": pages, "new_items": len(new_items), "matched": matched, "urgent": urgent,
            "send_errors": send_errors, "seeded": seeding}
