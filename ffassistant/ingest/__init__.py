"""Shared platform-dispatch sync, usable outside a Flask request context (the
API route and scripts/refresh_in_season.py both call this directly)."""

import sqlite3
from typing import Optional


def sync_league_from_platform(
    db: sqlite3.Connection,
    league_id: int,
    platform: str,
    platform_league_id,
    season: int,
    week: Optional[int] = None,
) -> None:
    """Resyncs one league's rosters (and, when `week` is given, player_status)
    from its platform. `week` should be None for a draft-day/offseason sync —
    each ingest module treats that as "skip status" rather than an error.
    """
    if platform == "sleeper":
        from ffassistant.ingest import sleeper as sleeper_ingest

        sleeper_ingest.sync_league(db, league_id, str(platform_league_id), season=season, week=week)
    elif platform == "espn":
        from ffassistant.ingest import espn as espn_ingest

        try:
            espn_numeric_id = int(platform_league_id)
        except ValueError:
            raise ValueError(
                f"ESPN league ID must be numeric (e.g. 360508, from the leagueId= URL param) — got {platform_league_id!r}"
            )
        espn_ingest.sync_league(db, league_id, espn_numeric_id, year=season, week=week)
    elif platform == "yahoo":
        from ffassistant.ingest import yahoo as yahoo_ingest

        yahoo_ingest.sync_league(db, league_id, str(platform_league_id), season=season, week=week)
    else:
        raise ValueError(f"Unknown platform: {platform}")

    team_count = db.execute("SELECT COUNT(*) AS c FROM teams WHERE league_id = ?", (league_id,)).fetchone()["c"]
    db.execute("UPDATE leagues SET team_count = ? WHERE league_id = ?", (team_count, league_id))
    db.commit()
