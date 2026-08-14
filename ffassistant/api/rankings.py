import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

rankings_bp = Blueprint("rankings", __name__, url_prefix="/api/leagues")

# Not league-scoped — draft rankings/tiers are global per season/scoring_format,
# so this gets its own prefix rather than sitting under /api/leagues.
rankings_admin_bp = Blueprint("rankings_admin", __name__, url_prefix="/api/rankings")


@rankings_bp.get("/<int:league_id>/rankings")
def get_rankings(league_id):
    """Always returns the full ranked player pool for this league — drafted or not.

    Deciding what's "available" is a view concern: the client already has the full
    draft-picks list (to render the board at all), so it filters drafted players
    out of the available-pool view itself rather than the server doing it twice.
    """
    db = get_db()
    scoring_format = request.args.get("scoring_format", "full_ppr")
    season = request.args.get("season", type=int) or datetime.date.today().year

    rows = db.execute(
        """
        SELECT r.rank, r.tier, r.adp, p.player_id, p.full_name, p.position, p.nfl_team, p.is_rookie,
               byes.bye_week, sos.playoff_sos_avg_opp_wins, sos.sos_rank, mt.tag AS manual_tag,
               rt.tag AS role_tag, it.implied_tt_full, it.offense_rank
        FROM rankings r
        JOIN players p ON p.player_id = r.player_id
        LEFT JOIN nfl_team_byes byes ON byes.team = p.nfl_team AND byes.season = r.season
        LEFT JOIN nfl_team_playoff_sos sos ON sos.team = p.nfl_team AND sos.season = r.season
        LEFT JOIN nfl_team_implied_totals it ON it.team = p.nfl_team AND it.season = r.season
        LEFT JOIN player_manual_tags mt ON mt.player_id = p.player_id
        LEFT JOIN player_role_tags rt ON rt.player_id = p.player_id
        WHERE r.ranking_type = 'draft' AND r.season = ? AND r.scoring_format = ?
        ORDER BY r.rank
        """,
        (season, scoring_format),
    ).fetchall()

    return jsonify([dict(r) for r in rows])


@rankings_admin_bp.post("/sync")
def sync_rankings():
    """On-demand refresh for the Draft tab's rank list — draft Top-300 for one
    scoring format, plus tiers (format-invariant, so always re-applied too).
    """
    db = get_db()
    body = request.get_json(silent=True) or {}
    season = int(body.get("season") or datetime.date.today().year)
    scoring_format = body.get("scoring_format", "full_ppr")

    from ffassistant.ingest import rankings as rankings_ingest
    from ffassistant.name_matching import list_unresolved

    try:
        rankings_ingest.sync_draft_rankings(db, season, scoring_format)
        rankings_ingest.sync_tiers(db, season)
    except Exception as e:
        abort(502, description=f"Rankings sync failed: {e}")

    player_count = db.execute(
        "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'draft' AND season = ? AND scoring_format = ?",
        (season, scoring_format),
    ).fetchone()["c"]
    tier_count = db.execute(
        "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'draft' AND season = ? "
        "AND scoring_format = ? AND tier IS NOT NULL",
        (season, scoring_format),
    ).fetchone()["c"]
    unresolved_count = len(list_unresolved(db, "rankings_provider"))
    synced_at = _last_synced_at(db, season, scoring_format)

    return jsonify(
        {
            "player_count": player_count,
            "tier_count": tier_count,
            "unresolved_count": unresolved_count,
            "synced_at": synced_at,
        }
    )


@rankings_admin_bp.get("/sync_status")
def get_sync_status():
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year
    scoring_format = request.args.get("scoring_format", "full_ppr")
    return jsonify({"synced_at": _last_synced_at(db, season, scoring_format)})


def _last_synced_at(db, season, scoring_format):
    """Draft rankings are a full-replace sync (see sync_draft_rankings), so the
    newest `fetched_at` among this season/scoring_format's rows is the last
    time this combination was actually refreshed — no separate log needed."""
    row = db.execute(
        "SELECT MAX(fetched_at) AS synced_at FROM rankings WHERE ranking_type = 'draft' "
        "AND season = ? AND scoring_format = ?",
        (season, scoring_format),
    ).fetchone()
    return row["synced_at"]
