import datetime

from flask import Blueprint, jsonify, request

from ffassistant.api import get_db

rankings_bp = Blueprint("rankings", __name__, url_prefix="/api/leagues")


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
        SELECT r.rank, r.tier, r.adp, p.player_id, p.full_name, p.position, p.nfl_team,
               byes.bye_week, sos.playoff_sos_avg_opp_wins, sos.sos_rank
        FROM rankings r
        JOIN players p ON p.player_id = r.player_id
        LEFT JOIN nfl_team_byes byes ON byes.team = p.nfl_team AND byes.season = r.season
        LEFT JOIN nfl_team_playoff_sos sos ON sos.team = p.nfl_team AND sos.season = r.season
        WHERE r.ranking_type = 'draft' AND r.season = ? AND r.scoring_format = ?
        ORDER BY r.rank
        """,
        (season, scoring_format),
    ).fetchall()

    return jsonify([dict(r) for r in rows])
