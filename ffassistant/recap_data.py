"""Gathers one week's box scores/matchup pairings/roster slots from the
database and runs them through ffassistant.recap's pure computation
functions, returning one consolidated dict — the same "assemble DB rows a
layer up, then hand them to the pure function" split as
ffassistant.api.in_season._compute_starters_for_league does for
ffassistant.starters.

Not a Flask blueprint (unlike ffassistant/api/*) — the weekly recap isn't
one of CLAUDE.md's five app-level sections (Draft | In-season | Exposure |
League settings | W-L), it's a generated artifact (HTML page + email +
GroupMe post) driven by a script/schedule rather than a UI tab.
"""

import sqlite3

from ffassistant.recap import (
    best_team_by_slot,
    biggest_win_and_closest_matchup,
    high_low_scores,
    matchup_details,
    matchup_results,
    next_week_preview,
    optimal_lineup_pct,
    start_sit_gaffes,
    team_projected_score,
    team_standings,
    team_weekly_scores,
    top_performers_by_position,
    upcoming_matchup_pairs,
    waiver_wire_difference_makers,
)


def gather_recap_data(conn: sqlite3.Connection, league_id: int, season: int, week: int) -> dict:
    """Every stat ffassistant.recap can currently compute for one
    league/season/week: {'league_id', 'season', 'week', 'team_names',
    'team_real_names', 'team_scores', 'high_low', 'matchups',
    'matchup_details', 'biggest_closest', 'top_performers', 'best_by_slot',
    'optimal_lineup_by_team', 'gaffes_by_team', 'waiver_wire', 'waiver_wire_synced',
    'owner_meta', 'standings', 'next_week'}. matchup_details is matchups enriched per side with
    score_by_checkpoint/top_players/performance_vs_projection — the full
    per-matchup story, ordered closest-margin first (is_matchup_of_the_week)
    — for the recap's tabbed matchup section. team_names prefers
    owners.display_nickname (the name
    that's actually safe to publish — e.g. "Johnny", never ESPN's "JFN"),
    falling back to teams.display_name, then teams.team_name; team_real_names
    is always the actual ESPN-configured team name regardless of any
    override — the recap shows both together. owner_meta carries the richer
    per-owner context (real_name/location/notes/sibling_team_id) from the
    owners table, keyed by team_id, for building things like the Next Week
    Preview or narrative commentary — {} for any league that hasn't
    populated that table (everything but TAMS, currently).

    Empty box scores (nothing synced yet for this league/season/week) isn't
    an error — every stat below just comes back empty/None, same as
    ffassistant.recap's own functions do for missing data, so a caller can
    render a "not synced yet" state rather than a crash. waiver_wire is []
    when weekly_free_agent_scores hasn't been synced for this week (which,
    per ffassistant.connectors.espn.get_free_agent_scores, is only ever
    possible for the current/most-recent season).

    standings is every team in the league (regardless of this
    week's sync status) ranked by ffassistant.recap.team_standings — ESPN's
    own wins/losses/points_for/points_against/playoff_pct/standing, not
    recomputed here. Each row also carries team_real_name (same
    owner-nickname-vs-actual-ESPN-name split as team_names/team_real_names
    above), so the standings table and Next Week Preview can show both
    together. next_week is {'week': week + 1, 'matchups': [...]} from
    ffassistant.recap.next_week_preview — the "matchups to watch" list for
    the Next Week Preview section, tagged for standings closeness, playoff
    bubble status, and (when that week's box scores/projections have been
    synced) a projected shootout. Both need their own syncs beyond what a
    single week's recap already requires: a teams resync (for
    wins/points_for/playoff_pct/standing to be current as of this week) and
    a weekly_matchups + weekly_box_scores sync for week + 1 (pairings and
    projections) — next_week's matchups list is [] and standings' playoff_pct/
    standing/projected_score fields are None until those are in place, same
    "just comes back empty" convention as the rest of this function.
    """
    box_rows = conn.execute(
        """
        SELECT wbs.team_id, wbs.player_id, wbs.slot_name, wbs.points,
               wbs.game_date, wbs.projected_points,
               p.full_name, p.position, p.is_rookie,
               COALESCE(o.display_nickname, t.display_name, t.team_name) AS team_name,
               t.team_name AS team_real_name
        FROM weekly_box_scores wbs
        JOIN players p ON p.player_id = wbs.player_id
        JOIN teams t ON t.team_id = wbs.team_id
        LEFT JOIN owners o ON o.team_id = t.team_id
        WHERE wbs.league_id = ? AND wbs.season = ? AND wbs.week = ?
        """,
        (league_id, season, week),
    ).fetchall()
    box_scores = [dict(r) for r in box_rows]

    team_names = {row["team_id"]: row["team_name"] for row in box_scores}
    # The actual ESPN-configured team name (e.g. "Bijan'd meAt"), independent of
    # the owner-nickname override above — standings shows both together.
    team_real_names = {row["team_id"]: row["team_real_name"] for row in box_scores}

    # Owner personalization (real name/location/family/flavor notes) — keyed
    # by team_id, for every team in the league regardless of whether box
    # scores have synced yet. Used for the Next Week Preview (siblings, same
    # city) and for whoever writes the week's narrative commentary. A league
    # with no owners rows populated yet (anything but TAMS, currently) just
    # gets an empty dict — nothing above depends on this being present.
    owner_meta = {
        row["team_id"]: {
            "real_name": row["real_name"],
            "display_nickname": row["display_nickname"],
            "location": row["location"],
            "notes": row["notes"],
            "sibling_team_id": row["sibling_team_id"],
        }
        for row in conn.execute(
            "SELECT o.* FROM owners o JOIN teams t ON t.team_id = o.team_id WHERE t.league_id = ?",
            (league_id,),
        )
    }

    roster_slots = {
        r["slot_name"]: r["slot_count"]
        for r in conn.execute("SELECT slot_name, slot_count FROM roster_slots WHERE league_id = ?", (league_id,))
    }

    free_agent_rows = conn.execute(
        """
        SELECT wfa.player_id, wfa.points, wfa.projected_points, p.full_name, p.position
        FROM weekly_free_agent_scores wfa
        JOIN players p ON p.player_id = wfa.player_id
        WHERE wfa.league_id = ? AND wfa.season = ? AND wfa.week = ?
        """,
        (league_id, season, week),
    ).fetchall()
    free_agent_scores = [dict(r) for r in free_agent_rows]

    matchup_pairs = [
        (r["team_id"], r["opponent_team_id"])
        for r in conn.execute(
            "SELECT team_id, opponent_team_id FROM weekly_matchups WHERE league_id = ? AND season = ? AND week = ?",
            (league_id, season, week),
        )
    ]

    by_team: dict[int, list[dict]] = {}
    for row in box_scores:
        by_team.setdefault(row["team_id"], []).append(row)

    team_scores = team_weekly_scores(box_scores)
    matchups = matchup_results(team_scores, team_names, matchup_pairs)

    # Standings — every team in the league (not scoped to this week's box
    # scores, since a team's record/playoff_pct comes from the teams table's
    # own last sync, not from anything gathered above).
    team_rows = [dict(r) for r in conn.execute(
        """
        SELECT t.team_id, COALESCE(o.display_nickname, t.display_name, t.team_name) AS team_name,
               t.team_name AS team_real_name,
               t.wins, t.losses, t.ties, t.points_for, t.points_against, t.playoff_pct, t.standing
        FROM teams t
        LEFT JOIN owners o ON o.team_id = t.team_id
        WHERE t.league_id = ?
        """,
        (league_id,),
    )]
    standings = team_standings(team_rows)

    # Next week's matchup pairings + projected scores — a separate sync target
    # (weekly_matchups/weekly_box_scores for week + 1) from this week's own
    # recap data above; both come back empty/None until that's been synced.
    next_week = week + 1
    next_week_pairs_raw = [
        (r["team_id"], r["opponent_team_id"])
        for r in conn.execute(
            "SELECT team_id, opponent_team_id FROM weekly_matchups WHERE league_id = ? AND season = ? AND week = ?",
            (league_id, season, next_week),
        )
    ]
    next_week_box_by_team: dict[int, list[dict]] = {}
    for r in conn.execute(
        "SELECT team_id, slot_name, projected_points FROM weekly_box_scores "
        "WHERE league_id = ? AND season = ? AND week = ?",
        (league_id, season, next_week),
    ):
        next_week_box_by_team.setdefault(r["team_id"], []).append(dict(r))
    projected_scores = {
        team_id: team_projected_score(rows) for team_id, rows in next_week_box_by_team.items()
    }

    return {
        "league_id": league_id,
        "season": season,
        "week": week,
        "team_names": team_names,
        "team_real_names": team_real_names,
        "team_scores": team_scores,
        "high_low": high_low_scores(team_scores, team_names),
        "matchups": matchups,
        "matchup_details": matchup_details(matchups, by_team),
        "biggest_closest": biggest_win_and_closest_matchup(matchups),
        "top_performers": top_performers_by_position(box_scores),
        "best_by_slot": best_team_by_slot(box_scores, team_names),
        "optimal_lineup_by_team": {
            team_id: optimal_lineup_pct(roster_slots, rows) for team_id, rows in by_team.items()
        },
        "gaffes_by_team": {team_id: start_sit_gaffes(rows) for team_id, rows in by_team.items()},
        "waiver_wire": waiver_wire_difference_makers(free_agent_scores, box_scores),
        # Distinguishes "nobody's run the sync yet" from "the sync ran, but
        # no free agent this week actually cleared a starting lineup's
        # floor" — both leave "waiver_wire" empty, but they're very
        # different situations to tell the reader about (see
        # recap_html._render_waiver_wire).
        "waiver_wire_synced": bool(free_agent_scores),
        "owner_meta": owner_meta,
        "standings": standings,
        "next_week": {
            "week": next_week,
            "matchups": next_week_preview(
                standings, upcoming_matchup_pairs(next_week_pairs_raw), projected_scores, owner_meta, week=next_week
            ),
        },
    }
