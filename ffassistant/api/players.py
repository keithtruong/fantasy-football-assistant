import datetime

from flask import Blueprint, jsonify, request

from ffassistant.api import get_db

players_bp = Blueprint("players", __name__, url_prefix="/api/players")


@players_bp.get("/search")
def search_players():
    """Autocomplete for pick entry: name substring match, excluding already-drafted
    players for the given league/season so the list narrows as the draft progresses.
    """
    db = get_db()
    query = request.args.get("q", "").strip()
    league_id = request.args.get("league_id", type=int)
    season = request.args.get("season", type=int) or datetime.date.today().year

    if len(query) < 2:
        return jsonify([])

    rows = db.execute(
        """
        SELECT player_id, full_name, position, nfl_team
        FROM players
        WHERE full_name LIKE ?
              AND (? IS NULL OR player_id NOT IN (
                  SELECT player_id FROM draft_picks
                  WHERE league_id = ? AND season = ? AND player_id IS NOT NULL
              ))
        ORDER BY full_name
        LIMIT 15
        """,
        (f"%{query}%", league_id, league_id, season),
    ).fetchall()

    return jsonify([dict(r) for r in rows])
