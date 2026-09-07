"""Read-only Sleeper connector. Sleeper's API is public — no auth/credentials needed."""

import json
from pathlib import Path

import requests

from ffassistant.config import REPO_ROOT

BASE_URL = "https://api.sleeper.app/v1"
PLAYERS_CACHE_PATH = REPO_ROOT / "data" / "sleeper_players.json"

# Sleeper's own codes for bench/defense differ from this project's schema vocabulary.
POSITION_MAP = {"DEF": "DST"}
SLOT_NAME_MAP = {"BN": "BENCH", "DEF": "DST"}


def _map_position(sleeper_position: str | None) -> str | None:
    return POSITION_MAP.get(sleeper_position, sleeper_position)


def get_nfl_state() -> dict:
    """Sleeper's public NFL state endpoint — the real current NFL week, season,
    and season_type ('pre'/'regular'/'post'). Not tied to any specific league
    or account — usable as a general "what week is it" source regardless of
    which platforms a league is actually on (see ffassistant.season).
    """
    resp = requests.get(f"{BASE_URL}/state/nfl", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_players_lookup(cache_path: Path = PLAYERS_CACHE_PATH, force_refresh: bool = False) -> dict:
    """Sleeper's full player table (~5MB, changes rarely) — cached locally after first fetch."""
    if cache_path.exists() and not force_refresh:
        return json.loads(cache_path.read_text())

    resp = requests.get(f"{BASE_URL}/players/nfl", timeout=30)
    resp.raise_for_status()
    players = resp.json()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(players))
    return players


def get_league_settings(sleeper_league_id: str) -> dict:
    """Returns {'team_count', 'scoring': {stat_key: points}, 'roster_slots': {slot_name: count}}."""
    resp = requests.get(f"{BASE_URL}/league/{sleeper_league_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()

    roster_slots: dict[str, int] = {}
    for slot in data.get("roster_positions", []):
        slot_name = SLOT_NAME_MAP.get(slot, slot)
        roster_slots[slot_name] = roster_slots.get(slot_name, 0) + 1

    return {
        "team_count": data.get("total_rosters"),
        "scoring": data.get("scoring_settings", {}),
        "roster_slots": roster_slots,
    }


def get_teams(sleeper_league_id: str) -> list[dict]:
    """One entry per team: platform_team_id, team_name, waiver_priority, wins/losses/ties,
    and its raw player-id list."""
    users_resp = requests.get(f"{BASE_URL}/league/{sleeper_league_id}/users", timeout=30)
    users_resp.raise_for_status()
    users = {u["user_id"]: u for u in users_resp.json()}

    rosters_resp = requests.get(f"{BASE_URL}/league/{sleeper_league_id}/rosters", timeout=30)
    rosters_resp.raise_for_status()

    teams = []
    for roster in rosters_resp.json():
        owner = users.get(roster.get("owner_id"), {})
        team_name = (owner.get("metadata") or {}).get("team_name") or owner.get("display_name", "Unknown")
        settings = roster.get("settings") or {}
        teams.append(
            {
                "platform_team_id": str(roster["roster_id"]),
                "team_name": team_name,
                "waiver_priority": settings.get("waiver_position"),
                "wins": settings.get("wins"),
                "losses": settings.get("losses"),
                "ties": settings.get("ties"),
                "player_ids": roster.get("players") or [],
            }
        )
    return teams


def get_matchups(sleeper_league_id: str, week: int) -> list[dict]:
    """This week's opponent pairings, one entry per side: {platform_team_id, opponent_platform_team_id}.

    Sleeper groups rosters into a pairing via a shared matchup_id — a roster on a bye
    week has a matchup_id shared with no one else and is simply skipped.
    """
    resp = requests.get(f"{BASE_URL}/league/{sleeper_league_id}/matchups/{week}", timeout=30)
    resp.raise_for_status()

    rosters_by_matchup: dict[int, list[str]] = {}
    for row in resp.json():
        rosters_by_matchup.setdefault(row["matchup_id"], []).append(str(row["roster_id"]))

    pairs = []
    for roster_ids in rosters_by_matchup.values():
        if len(roster_ids) != 2:
            continue  # bye week (lone roster) or unexpected grouping — skip rather than guess
        a, b = roster_ids
        pairs.append({"platform_team_id": a, "opponent_platform_team_id": b})
        pairs.append({"platform_team_id": b, "opponent_platform_team_id": a})
    return pairs


def get_roster_players(player_ids: list[str], players_lookup: dict) -> list[dict]:
    """Resolve Sleeper player IDs to structured info (name/position/team) via the cached lookup."""
    resolved = []
    for pid in player_ids:
        info = players_lookup.get(pid)
        if not info:
            continue
        full_name = info.get("full_name") or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
        resolved.append(
            {
                "source_player_id": pid,
                "full_name": full_name,
                "position": _map_position(info.get("position")),
                "nfl_team": info.get("team"),
                "injury_status": info.get("injury_status"),
            }
        )
    return resolved
