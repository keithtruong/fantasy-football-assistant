import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

in_season_bp = Blueprint("in_season", __name__, url_prefix="/api/leagues")

WEEKLY_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]
ROS_POSITIONS = ["QB", "RB", "WR", "TE"]  # DST/K aren't rest-of-season assets, per CLAUDE.md

AVAILABLE_LIMIT_PER_POSITION = 30


@in_season_bp.get("/<int:league_id>/in_season")
def get_in_season(league_id):
    """Rostered-vs-available view for Keith's own team, grouped by position.

    Mirrors the legacy 'Weekly Rank Eval' sheet: worst rostered players sort to
    the top (unranked/injured included, never dropped), available players are
    shown ungated by whether they'd actually be an upgrade.
    """
    db = get_db()
    view = request.args.get("view", "weekly")
    if view not in ("weekly", "ros"):
        abort(400, description="view must be 'weekly' or 'ros'")

    season = request.args.get("season", type=int) or datetime.date.today().year
    week = request.args.get("week", type=int)
    if view == "weekly" and week is None:
        abort(400, description="week is required for view=weekly")

    positions = WEEKLY_POSITIONS if view == "weekly" else ROS_POSITIONS
    ranking_type = "weekly" if view == "weekly" else "ros"

    my_team = db.execute(
        "SELECT team_id FROM teams WHERE league_id = ? AND is_mine = 1", (league_id,)
    ).fetchone()
    if my_team is None:
        abort(400, description="No team is marked as yours in this league yet — set it in League Settings")
    my_team_id = my_team["team_id"]

    rostered_rows = _fetch_rostered(db, my_team_id, ranking_type, season, week)
    available_rows = _fetch_available(db, league_id, ranking_type, season, week)

    result = {}
    for position in positions:
        rostered = [r for r in rostered_rows if r["position"] == position]
        available = [r for r in available_rows if r["position"] == position][:AVAILABLE_LIMIT_PER_POSITION]

        has_unranked_rostered = any(r["rank"] is None for r in rostered)
        ranked_rostered = [r["rank"] for r in rostered if r["rank"] is not None]
        worst_rostered_rank = max(ranked_rostered) if ranked_rostered else None

        for player in available:
            if has_unranked_rostered:
                player["beats_worst_rostered"] = True
            elif worst_rostered_rank is None:
                player["beats_worst_rostered"] = False  # nothing rostered here to compare against
            else:
                player["beats_worst_rostered"] = player["rank"] is not None and player["rank"] < worst_rostered_rank

        result[position] = {"rostered": rostered, "available": available}

    return jsonify(result)


def _fetch_rostered(db, team_id, ranking_type, season, week):
    rank_filter, rank_params = _rank_filter(ranking_type, week)
    pos_rank_join, pos_rank_params = _pos_rank_join(ranking_type, season, week)
    rows = db.execute(
        f"""
        SELECT p.player_id, p.full_name, p.position, r.rank, ps.status, pr.pos_rank
        FROM roster_spots rs
        JOIN players p ON p.player_id = rs.player_id
        LEFT JOIN rankings r ON r.player_id = p.player_id
              AND r.ranking_type = ? AND r.season = ? {rank_filter}
        LEFT JOIN player_status ps ON ps.player_id = p.player_id AND ps.season = ? AND ps.week = ?
        {pos_rank_join}
        WHERE rs.team_id = ?
        ORDER BY (r.rank IS NULL) DESC, r.rank DESC
        """,
        (ranking_type, season, *rank_params, season, week, *pos_rank_params, team_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_available(db, league_id, ranking_type, season, week):
    rank_filter, rank_params = _rank_filter(ranking_type, week)
    pos_rank_join, pos_rank_params = _pos_rank_join(ranking_type, season, week)
    rows = db.execute(
        f"""
        SELECT p.player_id, p.full_name, p.position, r.rank, pr.pos_rank
        FROM players p
        JOIN rankings r ON r.player_id = p.player_id
              AND r.ranking_type = ? AND r.season = ? {rank_filter}
        {pos_rank_join}
        WHERE p.player_id NOT IN (
            SELECT rs.player_id FROM roster_spots rs
            JOIN teams t ON t.team_id = rs.team_id
            WHERE t.league_id = ?
        )
        ORDER BY r.rank ASC
        """,
        (ranking_type, season, *rank_params, *pos_rank_params, league_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _rank_filter(ranking_type, week, alias="r"):
    """'ros' rankings never have a week (schema convention, same as 'draft'); only
    'weekly' rows need the week filter."""
    if ranking_type == "weekly":
        return f"AND {alias}.week = ?", (week,)
    return f"AND {alias}.week IS NULL", ()


def _pos_rank_join(ranking_type, season, week):
    """Rank-within-position, computed over the *full* ranked pool for this
    ranking_type/season/week — not just whichever rostered/available subset is
    being queried, so e.g. a QB's pos_rank reflects the whole league's QB order."""
    rank_filter, rank_params = _rank_filter(ranking_type, week, alias="r2")
    sql = f"""
        LEFT JOIN (
            SELECT r2.player_id,
                   RANK() OVER (PARTITION BY p2.position ORDER BY r2.rank ASC) AS pos_rank
            FROM rankings r2
            JOIN players p2 ON p2.player_id = r2.player_id
            WHERE r2.ranking_type = ? AND r2.season = ? AND r2.rank IS NOT NULL {rank_filter}
        ) pr ON pr.player_id = p.player_id
    """
    return sql, (ranking_type, season, *rank_params)
