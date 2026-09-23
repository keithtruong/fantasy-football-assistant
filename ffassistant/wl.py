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


def sync_league_season_record(conn: sqlite3.Connection, league_history_id: int, season: int) -> dict:
    """Keeps a league_seasons row's wins/losses/ties in sync with matchups
    for (league_history_id, season) — creates the row if it doesn't exist
    yet (buy_in/max_payout/actual_payout/finish_position all start NULL,
    Keith's own to fill in by hand — see CLAUDE.md's W-L tracking design) or
    updates just wins/losses/ties on an existing row, leaving those other
    columns untouched. A Guillotine-format league has no matchups rows at
    all (see guillotine_weeks instead), so this naturally leaves it at
    0/0/0 — same convention as its already-imported past seasons — without
    needing to special-case the format here.
    """
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN outcome = 'W' THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN outcome = 'L' THEN 1 ELSE 0 END), 0) AS losses,
            COALESCE(SUM(CASE WHEN outcome = 'T' THEN 1 ELSE 0 END), 0) AS ties
        FROM matchups WHERE league_history_id = ? AND season = ?
        """,
        (league_history_id, season),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO league_seasons (league_history_id, season, wins, losses, ties)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (league_history_id, season) DO UPDATE SET
            wins = excluded.wins, losses = excluded.losses, ties = excluded.ties
        """,
        (league_history_id, season, totals["wins"], totals["losses"], totals["ties"]),
    )
    conn.commit()
    return {
        "league_history_id": league_history_id,
        "season": season,
        "wins": totals["wins"],
        "losses": totals["losses"],
        "ties": totals["ties"],
    }


def autofill_from_platform_sync(conn: sqlite3.Connection, season: int, week: int) -> list[dict]:
    """Fills in a week's matchups rows for every active league_history entry
    that has a same-season platform league synced with a real result for
    Keith's own team. Matches league_history.name to leagues.name by the
    "<name> <season>" convention every active platform league follows (e.g.
    "BC1" -> "BC1 2026") — call sync_league_from_platform (or a full/rosters
    refresh) for the target week before this so that match has fresh data to
    read.

    Reads that week's score from weekly_matchups.points_for/points_against
    (each connector's own per-matchup total for that specific week — see
    ffassistant.connectors.{espn,yahoo,sleeper}.get_matchups), NOT
    teams.points_for/points_against, which is season-to-date cumulative and
    was the source of a real bug here: using it directly filled every week
    with the running total instead of that week's actual score.

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

        weekly = conn.execute(
            "SELECT points_for, points_against FROM weekly_matchups "
            "WHERE league_id = ? AND season = ? AND week = ? AND team_id = ?",
            (league["league_id"], season, week, team["team_id"]),
        ).fetchone()
        if weekly is None or not weekly["points_for"] or weekly["points_against"] is None:
            results.append({"league_history_name": history["name"], "status": "not_final_yet"})
            continue

        row = upsert_matchup(conn, history["league_history_id"], season, week, weekly["points_for"], weekly["points_against"])
        results.append({"league_history_name": history["name"], "status": "filled", **row})

    return results
