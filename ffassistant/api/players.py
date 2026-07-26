import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

players_bp = Blueprint("players", __name__, url_prefix="/api/players")

MANUAL_TAGS = ("sleeper", "shy_away")
ROLE_TAGS = ("bellcow", "committee", "one_injury_away")


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


@players_bp.put("/<int:player_id>/manual_tag")
def set_manual_tag(player_id):
    """Keith's personal target/avoid call on a player — set `tag` to null to clear."""
    db = get_db()
    payload = request.get_json(silent=True) or {}
    tag = payload.get("tag")

    if tag is None:
        db.execute("DELETE FROM player_manual_tags WHERE player_id = ?", (player_id,))
    else:
        if tag not in MANUAL_TAGS:
            abort(400, description=f"tag must be one of {MANUAL_TAGS} or null")
        db.execute(
            """
            INSERT INTO player_manual_tags (player_id, tag) VALUES (?, ?)
            ON CONFLICT (player_id) DO UPDATE SET tag = excluded.tag
            """,
            (player_id, tag),
        )
    db.commit()
    return "", 204


@players_bp.put("/<int:player_id>/role_tag")
def set_role_tag(player_id):
    """Keith's read on a backfield's touch-share situation — independent of the
    target/avoid manual_tag above (a player can carry both). Set `tag` to null to clear.
    """
    db = get_db()
    payload = request.get_json(silent=True) or {}
    tag = payload.get("tag")

    if tag is None:
        db.execute("DELETE FROM player_role_tags WHERE player_id = ?", (player_id,))
    else:
        if tag not in ROLE_TAGS:
            abort(400, description=f"tag must be one of {ROLE_TAGS} or null")
        db.execute(
            """
            INSERT INTO player_role_tags (player_id, tag) VALUES (?, ?)
            ON CONFLICT (player_id) DO UPDATE SET tag = excluded.tag
            """,
            (player_id, tag),
        )
    db.commit()
    return "", 204
