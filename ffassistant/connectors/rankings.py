"""Read-only connectors for the (generic, never-named) rankings provider's feeds.

Source URLs, the session cookie, and any provider-specific IDs live only in the
local, gitignored .rankings_config.json (see config.get_rankings_config()) —
never in this file, per CLAUDE.md's confidentiality rule.

Two distinct fetch mechanisms:
- Draft Top-300 (per scoring format): rows embedded as JSON inside a
  server-rendered <script> block, requires the session cookie.
    window.SOME_DATASET_VAR = JSON.parse(`{"rows":[...]}`)
- Weekly rankings (per position): a public JSONP endpoint embedded by a
  third-party widget on the provider's site. No cookie needed — confirmed
  it returns data with no session/auth at all.
    FPW.rankingsCB({"players":[...]})
"""

import html
import json
import re

import requests

from ffassistant.config import get_rankings_config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_JSON_MARKER = "JSON.parse(`{"


def _extract_rows(html: str) -> list[dict]:
    """Pull the embedded rows array out of the page's server-rendered HTML."""
    start = html.find(_JSON_MARKER)
    if start == -1:
        raise ValueError("Ranking data marker not found in page — session cookie may be invalid/expired")

    json_start = html.index("{", start)

    depth = 0
    in_string = False
    escape_next = False
    json_end = -1
    for i in range(json_start, len(html)):
        c = html[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\" and in_string:
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        raise ValueError("Could not find end of ranking data JSON block")

    data = json.loads(html[json_start:json_end])
    rows = data.get("rows", [])
    if not rows:
        raise ValueError("No ranking rows found — session cookie may be invalid/expired")
    return rows


def _fetch_with_cookie(url: str) -> str:
    config = get_rankings_config()
    cookies = {}
    name, _, value = config["cookie"].partition("=")
    cookies[name.strip()] = value.strip()

    resp = requests.get(url, headers=_HEADERS, cookies=cookies, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def get_draft_rankings(scoring_format: str) -> list[dict]:
    """Fetch the draft Top-300 for one scoring format (see .rankings_config.json's draft_urls keys).

    Returns a list of dicts: full_name, position, nfl_team, rank, adp, position_rank.
    """
    config = get_rankings_config()
    url = config["draft_urls"][scoring_format]
    text = _fetch_with_cookie(url)

    rows = _extract_rows(text)

    rankings = []
    for row in rows:
        player = row.get("player")
        rank = row.get("etrRank")
        if not player or rank in (None, ""):
            continue
        rankings.append(
            {
                "full_name": player,
                "position": (row.get("position") or "").upper() or None,
                "nfl_team": (row.get("team") or "").upper() or None,
                "rank": int(rank),
                "adp": float(row["adp"]) if row.get("adp") not in (None, "") else None,
                "position_rank": row.get("posRankEtr") or None,
            }
        )
    return rankings


TIER_POSITIONS = ["QB", "RB", "WR", "TE"]  # no tier pages published for K/DST

_TIER_HEADER = re.compile(r"^Tier (\d+):\s*(.*)$")
_POSITION_RANK_SUFFIX = re.compile(r"\s*\([A-Z]+\d*\)\s*$")
_TAG = re.compile(r"<[^>]+>")
_P1_PARAGRAPH = re.compile(r'<p class="p1">(.*?)</p>', re.DOTALL)


def get_tiers(position: str) -> list[dict]:
    """Fetch one position's tier breakdown (an editorial article, not a data table).

    Returns a list of dicts: full_name, tier. Tiers not yet published by the provider
    are skipped (empty after the "Tier N:" label) rather than treated as an error —
    that's normal mid-offseason, not a broken fetch.
    """
    config = get_rankings_config()
    url = config["tier_urls"][position]
    text = _fetch_with_cookie(url)

    tiers = []
    for paragraph_html in _P1_PARAGRAPH.findall(text):
        stripped = html.unescape(_TAG.sub("", paragraph_html)).strip()
        match = _TIER_HEADER.match(stripped)
        if not match:
            continue  # not a tier header, just analysis prose

        tier_num = int(match.group(1))
        remainder = match.group(2).strip()
        if not remainder:
            continue  # tier not yet published

        for segment in remainder.split(">"):
            player_name = _POSITION_RANK_SUFFIX.sub("", segment).strip()
            if player_name:
                tiers.append({"full_name": player_name, "tier": tier_num})
    return tiers


WEEKLY_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]


def _parse_jsonp(text: str) -> dict:
    """Strip a 'callback_name({...})' JSONP wrapper down to the raw JSON payload."""
    start = text.index("(") + 1
    end = text.rindex(")")
    return json.loads(text[start:end])


def get_weekly_rankings(season: int, week: int, position: str) -> list[dict]:
    """Fetch one position's weekly rankings for a season/week. Public endpoint — no cookie needed.

    Returns a list of dicts: full_name, position, nfl_team, rank, position_rank, bye_week, opponent.
    """
    weekly_config = get_rankings_config()["weekly"]
    params = {
        "callback": "FPW.rankingsCB",
        "position": position,
        "sport": "NFL",
        "year": season,
        "week": week,
        "id": weekly_config["expert_id"],
        "scoring": weekly_config["scoring"],
        "type": "WEEKLY",
    }
    resp = requests.get(weekly_config["base_url"], params=params, timeout=30)
    resp.raise_for_status()
    data = _parse_jsonp(resp.text)

    rankings = []
    for player in data.get("players") or []:
        rank = player.get("rank")
        if not player.get("player_name") or rank in (None, ""):
            continue
        rankings.append(
            {
                "full_name": player["player_name"],
                "position": (player.get("player_positions") or position).upper(),
                "nfl_team": (player.get("player_team_id") or "").upper() or None,
                "rank": int(rank),
                "position_rank": player.get("pos_rank"),
                "bye_week": int(player["bye_week"]) if player.get("bye_week") else None,
                "opponent": player.get("opponent"),
            }
        )
    return rankings
