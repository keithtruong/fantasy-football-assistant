import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db
from ffassistant.draft_logic import compute_pick_slot

draft_picks_bp = Blueprint("draft_picks", __name__, url_prefix="/api/leagues/<int:league_id>/draft_picks")


@draft_picks_bp.get("")
def list_picks(league_id):
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year

    rows = db.execute(
        """
        SELECT dp.draft_pick_id, dp.round, dp.pick_number, dp.team_id, t.team_name,
               dp.player_id, p.full_name, p.position, dp.picked_at
        FROM draft_picks dp
        JOIN teams t ON t.team_id = dp.team_id
        LEFT JOIN players p ON p.player_id = dp.player_id
        WHERE dp.league_id = ? AND dp.season = ?
        ORDER BY dp.pick_number
        """,
        (league_id, season),
    ).fetchall()

    return jsonify({"picks": [dict(r) for r in rows], "on_the_clock": _on_the_clock(db, league_id, season)})


@draft_picks_bp.post("")
def record_pick(league_id):
    db = get_db()
    body = request.get_json(force=True)
    player_id = body.get("player_id")
    season = body.get("season") or datetime.date.today().year
    if not player_id:
        abort(400, description="player_id is required")

    clock = _on_the_clock(db, league_id, season)

    row = db.execute(
        "INSERT INTO draft_picks (league_id, season, round, pick_number, team_id, player_id) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING draft_pick_id",
        (league_id, season, clock["round"], clock["pick_number"], clock["team_id"], player_id),
    ).fetchone()
    db.commit()

    return jsonify({"draft_pick_id": row["draft_pick_id"], **clock}), 201


@draft_picks_bp.put("/<int:pick_id>")
def edit_pick(pick_id, league_id):
    db = get_db()
    body = request.get_json(force=True)
    player_id = body.get("player_id")
    if not player_id:
        abort(400, description="player_id is required")

    result = db.execute(
        "UPDATE draft_picks SET player_id = ? WHERE draft_pick_id = ? AND league_id = ?",
        (player_id, pick_id, league_id),
    )
    if result.rowcount == 0:
        abort(404, description="Pick not found")
    db.commit()
    return jsonify({"draft_pick_id": pick_id, "player_id": player_id})


@draft_picks_bp.delete("")
def clear_picks(league_id):
    """Wipes every pick for this league/season — a mock-draft reset, not an undo.
    Confirmation lives client-side; this endpoint does the deletion unconditionally.
    """
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year
    db.execute("DELETE FROM draft_picks WHERE league_id = ? AND season = ?", (league_id, season))
    db.commit()
    return "", 204


@draft_picks_bp.delete("/<int:pick_id>")
def undo_pick(pick_id, league_id):
    """Only the most recent pick can be undone — avoids renumbering every later pick."""
    db = get_db()
    pick = db.execute(
        "SELECT season, pick_number FROM draft_picks WHERE draft_pick_id = ? AND league_id = ?",
        (pick_id, league_id),
    ).fetchone()
    if pick is None:
        abort(404, description="Pick not found")

    latest = db.execute(
        "SELECT MAX(pick_number) AS max_pick FROM draft_picks WHERE league_id = ? AND season = ?",
        (league_id, pick["season"]),
    ).fetchone()
    if pick["pick_number"] != latest["max_pick"]:
        abort(409, description="Only the most recent pick can be undone")

    db.execute("DELETE FROM draft_picks WHERE draft_pick_id = ?", (pick_id,))
    db.commit()
    return "", 204


def _on_the_clock(db, league_id, season) -> dict:
    league = db.execute("SELECT team_count FROM leagues WHERE league_id = ?", (league_id,)).fetchone()
    if league is None:
        abort(404, description="League not found")

    existing = db.execute(
        "SELECT COUNT(*) AS c FROM draft_picks WHERE league_id = ? AND season = ?",
        (league_id, season),
    ).fetchone()
    pick_number = existing["c"] + 1
    round_num, draft_position = compute_pick_slot(pick_number, league["team_count"])

    team = db.execute(
        "SELECT team_id, team_name FROM teams WHERE league_id = ? AND draft_position = ?",
        (league_id, draft_position),
    ).fetchone()
    if team is None:
        abort(400, description=f"No team found at draft_position {draft_position} for this league")

    return {
        "pick_number": pick_number,
        "round": round_num,
        "team_id": team["team_id"],
        "team_name": team["team_name"],
    }
