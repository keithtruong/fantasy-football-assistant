from flask import Blueprint, abort, jsonify

from ffassistant.api import get_db

news_bp = Blueprint("news", __name__, url_prefix="/api/news")


@news_bp.post("/sync")
def sync_news():
    """On-demand refresh for player news headlines (not league/season/week scoped).

    Re-ingests whatever a scheduled Cowork task last dropped (see
    ffassistant.ingest.news.sync_player_news_from_file) rather than calling
    the Anthropic API directly — extraction AND digest synthesis both read
    from files a Cowork task drops on its own schedule, so this never calls
    the metered API, but means this button reflects Cowork's last run(s), not
    a fresh extraction/digest.
    """
    db = get_db()

    from ffassistant.ingest.news import sync_player_news_from_file

    try:
        stats = sync_player_news_from_file(db)
    except Exception as e:
        abort(502, description=f"Player news sync failed: {e}")

    player_count = db.execute(
        "SELECT COUNT(DISTINCT player_id) AS c FROM player_news"
    ).fetchone()["c"]
    headline_count = db.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"]

    return jsonify(
        {
            "player_count": player_count,
            "headline_count": headline_count,
            "synced_at": _last_synced_at(db),
            # Nonzero here usually means a Rotoworld-pull Cowork trigger's
            # prompt stopped extracting the permalink, not that there was no
            # news — see ffassistant.refresh.refresh_news for the same signal
            # surfaced in the scheduled refresh log.
            "skipped_no_link": stats["skipped_no_link"],
        }
    )


@news_bp.get("/sync_status")
def get_sync_status():
    db = get_db()
    headline_count = db.execute("SELECT COUNT(*) AS c FROM player_news").fetchone()["c"]
    return jsonify({"headline_count": headline_count, "synced_at": _last_synced_at(db)})


def _last_synced_at(db):
    row = db.execute("SELECT MAX(fetched_at) AS synced_at FROM player_news").fetchone()
    return row["synced_at"]
