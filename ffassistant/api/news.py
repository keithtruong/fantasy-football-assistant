from flask import Blueprint, abort, jsonify

from ffassistant.api import get_db

news_bp = Blueprint("news", __name__, url_prefix="/api/news")


@news_bp.post("/sync")
def sync_news():
    """On-demand refresh for player news headlines (not league/season/week scoped)."""
    db = get_db()

    from ffassistant.ingest.news import sync_player_news

    try:
        sync_player_news(db)
    except Exception as e:
        abort(502, description=f"Player news sync failed: {e}")

    player_count = db.execute(
        "SELECT COUNT(DISTINCT player_id) AS c FROM player_news"
    ).fetchone()["c"]
    headline_count = db.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"]

    return jsonify(
        {"player_count": player_count, "headline_count": headline_count, "synced_at": _last_synced_at(db)}
    )


@news_bp.get("/sync_status")
def get_sync_status():
    db = get_db()
    headline_count = db.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"]
    return jsonify({"headline_count": headline_count, "synced_at": _last_synced_at(db)})


def _last_synced_at(db):
    row = db.execute("SELECT MAX(fetched_at) AS synced_at FROM player_news").fetchone()
    return row["synced_at"]
