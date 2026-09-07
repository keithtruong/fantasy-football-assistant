import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db
from ffassistant import season as season_mod

season_bp = Blueprint("season", __name__, url_prefix="/api/season")


@season_bp.get("/<int:season>")
def get_season(season):
    db = get_db()
    week1_start = season_mod.get_week1_start_date(db, season)
    return jsonify(
        {
            "season": season,
            "week1_start_date": week1_start.isoformat() if week1_start else None,
            "current_week": season_mod.smart_current_week(db, season),
        }
    )


@season_bp.put("/<int:season>")
def put_season(season):
    db = get_db()
    body = request.get_json(silent=True) or {}
    raw_date = body.get("week1_start_date")
    if not raw_date:
        abort(400, description="week1_start_date is required (ISO format, e.g. 2026-09-09)")

    try:
        week1_start = datetime.date.fromisoformat(raw_date)
    except ValueError:
        abort(400, description=f"week1_start_date must be an ISO date (YYYY-MM-DD) — got {raw_date!r}")

    season_mod.set_week1_start_date(db, season, week1_start)
    return jsonify(
        {
            "season": season,
            "week1_start_date": week1_start.isoformat(),
            "current_week": season_mod.smart_current_week(db, season),
        }
    )
