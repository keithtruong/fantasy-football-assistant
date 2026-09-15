"""Shared W-L logic used by both the manual-entry API route
(ffassistant.api.wl.put_matchup) and the platform-sync autofill below.

autofill_from_platform_sync() is the "in-season automation candidate"
CLAUDE.md flags as not yet built for PF/PA entry — it fills a week's
matchups rows from whatever the ESPN/Yahoo/Sleeper connectors already synced
onto teams.wins/losses/points_for/points_against, rather than Keith typing
each league's result in by hand every week.
"""

import sqlite3


def derive_outcome(points_for: float, points_against: float) -> str:
    if points_for > points_against:
        return "W"
    if points_for < points_against:
        return "L"
    return "T"


def upsert_matchup(
    conn: sqlite3.Connection,
    league_history_id: int,
    season: int,
    week: int,
    points_for: float,
    points_against: float,
    playoff_round: str | None = None,
) -> dict:
    outcome = derive_outcome(points_for, points_against)
    conn.execute(
        """
        INSERT INTO matchups (league_history_id, season, week, points_for, points_against, outcome, playoff_round)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (league_history_id, season, week) DO UPDATE SET
            points_for = excluded.points_for,
            points_against = excluded.points_against,
            outcome = excluded.outcome,
            playoff_round = excluded.playoff_round
        """,
        (league_history_id, season, week, points_for, points_against, outcome, playoff_round),
    )
    conn.commit()
    return {
        "league_history_id": league_history_id,
        "season": season,
        "week": week,
        "points_for": points_for,
        "points_against": points_against,
        "outcome": outcome,
        "playoff_round": playoff_round,
    }


def upsert_guillotine_week(
    conn: sqlite3.Connection,
    league_history_id: int,
    season: int,
    week: int,
    points_for: float,
    eliminated_points: float,
    rank: int,
    remaining_count: int,
) -> dict:
    conn.execute(
        """
        INSERT INTO guillotine_weeks
            (league_history_id, season, week, points_for, eliminated_points, rank, remaining_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (league_history_id, season, week) DO UPDATE SET
            points_for = excluded.points_for,
            eliminated_points = excluded.eliminated_points,
            rank = excluded.rank,
            remaining_count = excluded.remaining_count
        """,
        (league_history_id, season, week, points_for, eliminated_points, rank, remaining_count),
    )
    conn.commit()
    return {
        "league_history_id": league_history_id,
        "season": season,
        "week": week,
        "points_for": points_for,
        "eliminated_points": eliminated_points,
        "rank": rank,
        "remaining_count": remaining_count,
    }


def autofill_from_platform_sync(conn: sqlite3.Connection, season: int, week: int) -> list[dict]:
    """Fills in a week's matchups rows for every active league_history entry
    that has a same-season platform league synced with a real result for
    Keith's own team. Matches league_history.name to leagues.name by the
    "<name> <season>" convention every active platform league follows (e.g.
    "BC1" -> "BC1 2026") — call sync_league_from_platform (or a full/rosters
    refresh) for the target week before this so that match has fresh data to
    read.

    Does not itself detect "is this week actually final" — none of the three
    connectors expose that directly. Instead it treats points_for == 0.0 (or
    missing) as "not synced/finalized yet" and skips it, since a real
    completed fantasy week is never exactly zero points; ESPN and Yahoo both
    report 0.0 (not None) for an unfinalized week, so None alone isn't a
    reliable enough signal.

    A league with no traditional win/loss record at all (a Guillotine-style
    league — survival-by-elimination, not head-to-head; see
    ffassistant.connectors.yahoo.get_teams) is skipped outright: its
    wins/losses come back None from every connector, and there's no source
    for what "win"/"loss" should even mean there — needs a manual call, not
    an autofill guess.

    Returns one dict per league_history row: {league_history_name, status,
    ...} where status is "filled", "not_final_yet", "no_traditional_record",
    "no_my_team_flagged", or "no_platform_match". A "filled" entry also
    carries upsert_matchup()'s return fields.
    """
    leagues_by_name = {row["name"]: row for row in conn.execute("SELECT * FROM leagues WHERE active = 1")}
    history_rows = conn.execute("SELECT * FROM league_history WHERE active = 1 ORDER BY name").fetchall()

    results = []
    for history in history_rows:
        league = leagues_by_name.get(f"{history['name']} {season}")
        if league is None:
            results.append({"league_history_name": history["name"], "status": "no_platform_match"})
            continue

        team = conn.execute(
            "SELECT * FROM teams WHERE league_id = ? AND is_mine = 1", (league["league_id"],)
        ).fetchone()
        if team is None:
            results.append({"league_history_name": history["name"], "status": "no_my_team_flagged"})
            continue

        if team["wins"] is None or team["losses"] is None:
            results.append({"league_history_name": history["name"], "status": "no_traditional_record"})
            continue

        if not team["points_for"] or team["points_against"] is None:
            results.append({"league_history_name": history["name"], "status": "not_final_yet"})
            continue

        row = upsert_matchup(conn, history["league_history_id"], season, week, team["points_for"], team["points_against"])
        results.append({"league_history_name": history["name"], "status": "filled", **row})

    return results
