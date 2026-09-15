"""Guillotine (survivor-elimination) league automation.

Yahoo's own per-team `rank_week`/`points_from_chop` fields on
league.standings() looked purpose-built for exactly this, but they're
live/current-week-only: standings() takes no `week` parameter, and
current_week() already advances to the next week before those fields would
ever reflect the one that just finished (confirmed by inspection the morning
after a week closed -- both fields were flat 0.00 for every team, and
current_week() had already moved on).

So this instead snapshots every team's cumulative points_for on every weekly
sync (guillotine_team_snapshots -- points_for itself is reliable, confirmed
against a real result) and derives each week's rank/eliminated score itself,
as the delta against the prior week's snapshot, tracking who's still alive
independently of Yahoo's own standings() list (which was still listing an
already-eliminated team's full 18-team field a full day after that week
closed, so "did the low scorer disappear from standings() yet" isn't a
reliable signal either).

Known simplifying assumptions -- fine for the one league this applies to
today, revisit if a league breaks the pattern: exactly one elimination per
week starting week 1, and a tie for lowest score isn't specially resolved
(picks whichever tied team sorted first -- may not match Yahoo's own
tiebreaker).
"""

import sqlite3

from ffassistant.connectors.yahoo import get_standings
from ffassistant.wl import upsert_guillotine_week


def save_team_snapshot(conn: sqlite3.Connection, league_id: int, season: int, week: int, standings: list[dict]) -> None:
    """Full-replace per (league_id, season, week), same convention as
    weekly_box_scores/weekly_free_agent_scores. `standings` is
    ffassistant.connectors.yahoo.get_standings's shape:
    [{platform_team_id, team_name, points_for}, ...]."""
    conn.execute(
        "DELETE FROM guillotine_team_snapshots WHERE league_id = ? AND season = ? AND week = ?",
        (league_id, season, week),
    )
    conn.executemany(
        """
        INSERT INTO guillotine_team_snapshots
            (league_id, season, week, platform_team_id, team_name, cumulative_points_for)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(league_id, season, week, s["platform_team_id"], s["team_name"], s["points_for"]) for s in standings],
    )
    conn.commit()


def compute_week_result(
    conn: sqlite3.Connection, league_id: int, season: int, week: int, my_platform_team_id: str
) -> dict | None:
    """Replays week 1..`week` from stored snapshots, tracking the surviving
    field itself (starting from every team in week 1's own snapshot) and
    eliminating that week's lowest scorer from the field each time it moves
    to the next week.

    Returns None if any snapshot from week 1 through `week` is missing, or if
    `my_platform_team_id` isn't in the field for `week` (already eliminated,
    or never appeared). Otherwise returns {points_for, eliminated_points,
    rank, remaining_count} for `my_platform_team_id` at `week`, ready for
    ffassistant.wl.upsert_guillotine_week.
    """
    snapshots_by_week = {}
    for wk in range(1, week + 1):
        rows = conn.execute(
            "SELECT platform_team_id, cumulative_points_for FROM guillotine_team_snapshots "
            "WHERE league_id = ? AND season = ? AND week = ?",
            (league_id, season, wk),
        ).fetchall()
        if not rows:
            return None
        snapshots_by_week[wk] = {r["platform_team_id"]: r["cumulative_points_for"] for r in rows}

    field = set(snapshots_by_week[1].keys())
    result = None

    for wk in range(1, week + 1):
        prior = snapshots_by_week[wk - 1] if wk > 1 else {}
        current = snapshots_by_week[wk]
        deltas = {tid: current[tid] - prior.get(tid, 0.0) for tid in field if tid in current}
        if not deltas:
            return None

        ranked = sorted(deltas.items(), key=lambda kv: kv[1], reverse=True)
        rank_by_team = {tid: i + 1 for i, (tid, _) in enumerate(ranked)}
        eliminated_team, eliminated_points = ranked[-1]

        if wk == week:
            if my_platform_team_id not in deltas:
                return None
            result = {
                "points_for": deltas[my_platform_team_id],
                "eliminated_points": eliminated_points,
                "rank": rank_by_team[my_platform_team_id],
                "remaining_count": len(field),
            }

        field = field - {eliminated_team}

    return result


def sync_and_fill_week(conn: sqlite3.Connection, season: int, week: int) -> list[dict]:
    """The network-touching counterpart to ffassistant.wl.autofill_from_platform_sync,
    kept separate since a Guillotine week's result shape (points_for/
    eliminated_points/rank/remaining_count) is fundamentally different from a
    head-to-head one (outcome/points_against) and needs its own live Yahoo
    call (get_standings) beyond what the ordinary teams-table sync already
    captures.

    Only Yahoo is supported today -- the one Guillotine league on record is a
    Yahoo league, and there's no ESPN/Sleeper connector support for this
    league type to fall back on.

    Returns one dict per active `format = 'guillotine'` league_history row:
    {league_history_name, status, ...} where status is "filled",
    "not_enough_history" (this week's or an earlier week's snapshot couldn't
    be resolved into a result -- often just "check back once the field
    settles"), "no_my_team_flagged", "unsupported_platform", or
    "no_platform_match". A "filled" entry also carries
    upsert_guillotine_week()'s return fields.
    """
    leagues_by_name = {row["name"]: row for row in conn.execute("SELECT * FROM leagues WHERE active = 1")}
    history_rows = conn.execute(
        "SELECT * FROM league_history WHERE active = 1 AND format = 'guillotine' ORDER BY name"
    ).fetchall()

    results = []
    for history in history_rows:
        league = leagues_by_name.get(f"{history['name']} {season}")
        if league is None:
            results.append({"league_history_name": history["name"], "status": "no_platform_match"})
            continue

        if league["platform"] != "yahoo":
            results.append({"league_history_name": history["name"], "status": "unsupported_platform"})
            continue

        team = conn.execute(
            "SELECT * FROM teams WHERE league_id = ? AND is_mine = 1", (league["league_id"],)
        ).fetchone()
        if team is None:
            results.append({"league_history_name": history["name"], "status": "no_my_team_flagged"})
            continue

        standings = get_standings(league["platform_league_id"])
        save_team_snapshot(conn, league["league_id"], season, week, standings)

        result = compute_week_result(conn, league["league_id"], season, week, team["platform_team_id"])
        if result is None:
            results.append({"league_history_name": history["name"], "status": "not_enough_history"})
            continue

        row = upsert_guillotine_week(
            conn,
            history["league_history_id"],
            season,
            week,
            result["points_for"],
            result["eliminated_points"],
            result["rank"],
            result["remaining_count"],
        )
        results.append({"league_history_name": history["name"], "status": "filled", **row})

    return results
