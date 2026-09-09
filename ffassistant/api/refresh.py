import datetime

from flask import Blueprint, jsonify, request

from ffassistant.api import get_db

# Not league-scoped — this refreshes every active league at once (rosters,
# weekly/ROS rankings, player news), same work as scripts/refresh_in_season.py's
# scheduled desktop run, so it doesn't live under /api/leagues/<id>.
refresh_bp = Blueprint("refresh", __name__, url_prefix="/api")


@refresh_bp.post("/refresh_all")
def refresh_all():
    """On-demand "Refresh All Leagues" — rosters/status/record/matchup for every
    active platform league, plus weekly/ROS rankings and player news, in one call.

    Never fails outright: each piece is independently best-effort (see
    ffassistant.refresh.run_full_refresh), so a 200 here can still carry
    per-league or per-format failures in the response body for the UI to surface.
    Lands in the same data/refresh_log.txt as the scheduled desktop run.
    """
    db = get_db()
    body = request.get_json(silent=True) or {}
    season = int(body.get("season") or datetime.date.today().year)
    week = body.get("week")
    week = int(week) if week is not None else None

    from ffassistant.refresh import run_full_refresh

    summary = run_full_refresh(db, season=season, week=week)
    return jsonify(summary)


@refresh_bp.post("/refresh_rosters")
def refresh_rosters_only():
    """On-demand "Refresh All Rosters" — rosters/status/record/matchup for every
    active league, skipping weekly/ROS rankings and player news. For a quick
    "did anyone make a move" check that doesn't need a rankings-provider hit
    (and isn't blocked by one, e.g. an expired cookie).
    """
    db = get_db()
    body = request.get_json(silent=True) or {}
    season = int(body.get("season") or datetime.date.today().year)
    week = body.get("week")
    week = int(week) if week is not None else None

    from ffassistant.refresh import run_rosters_only_refresh

    summary = run_rosters_only_refresh(db, season=season, week=week)
    return jsonify(summary)
