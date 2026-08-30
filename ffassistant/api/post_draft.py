import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

post_draft_bp = Blueprint("post_draft", __name__, url_prefix="/api/leagues/<int:league_id>/post_draft")

# Pick-vs-snapshot-rank gap worth flagging visually. Mirrors the Draft tab's
# Reach/Wait ADP-gap tag but tighter (5 picks, not ~12) — this is a one-time
# after-the-fact review of a specific draft, not a live "safe to wait" call.
NOTABLE_PICK_RANK_GAP = 5


@post_draft_bp.get("")
def get_post_draft(league_id):
    """Post-draft review for one league/season: every pick alongside the rank it
    held in the frozen snapshot (see complete_draft), a value/reach indicator,
    and Keith's own notes. Returns completed=false with an empty snapshot join
    until the draft has actually been marked complete.
    """
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year

    completion = db.execute(
        "SELECT scoring_format, completed_at FROM draft_completions WHERE league_id = ? AND season = ?",
        (league_id, season),
    ).fetchone()

    rows = db.execute(
        """
        SELECT dp.draft_pick_id, dp.round, dp.pick_number, dp.notes, dp.team_id,
               COALESCE(t.display_name, t.team_name) AS team_name,
               p.player_id, p.full_name, p.position,
               s.rank AS snapshot_rank, s.tier AS snapshot_tier, s.adp AS snapshot_adp
        FROM draft_picks dp
        JOIN teams t ON t.team_id = dp.team_id
        LEFT JOIN players p ON p.player_id = dp.player_id
        LEFT JOIN draft_analysis_snapshots s
               ON s.league_id = dp.league_id AND s.season = dp.season AND s.player_id = dp.player_id
        WHERE dp.league_id = ? AND dp.season = ?
        ORDER BY dp.pick_number
        """,
        (league_id, season),
    ).fetchall()

    picks = []
    for row in rows:
        pick = dict(row)
        if pick["snapshot_rank"] is not None:
            # Positive -> pick_number came after (worse than) snapshot_rank, i.e.
            # the player fell — value. Negative -> pick_number came before
            # (better than) snapshot_rank, i.e. taken ahead of schedule — a reach.
            diff = pick["pick_number"] - pick["snapshot_rank"]
            pick["rank_diff"] = diff
            pick["notable"] = abs(diff) >= NOTABLE_PICK_RANK_GAP
        else:
            pick["rank_diff"] = None
            pick["notable"] = False
        picks.append(pick)

    return jsonify(
        {
            "completed": completion is not None,
            "completed_at": completion["completed_at"] if completion else None,
            "scoring_format": completion["scoring_format"] if completion else None,
            "picks": picks,
        }
    )


@post_draft_bp.post("/complete")
def complete_draft(league_id):
    """Marks this league/season's draft complete and freezes the current draft
    rankings pool for the given scoring_format into draft_analysis_snapshots.
    Safe to call again (e.g. to correct the scoring_format) — replaces any
    existing snapshot/completion for this league/season rather than erroring.
    """
    db = get_db()
    body = request.get_json(force=True)
    season = int(body.get("season") or datetime.date.today().year)
    scoring_format = body.get("scoring_format")
    if not scoring_format:
        abort(400, description="scoring_format is required")

    league = db.execute("SELECT league_id FROM leagues WHERE league_id = ?", (league_id,)).fetchone()
    if league is None:
        abort(404, description="League not found")

    pick_count = db.execute(
        "SELECT COUNT(*) AS c FROM draft_picks WHERE league_id = ? AND season = ?",
        (league_id, season),
    ).fetchone()["c"]
    if pick_count == 0:
        abort(400, description="No draft picks recorded for this league/season yet")

    db.execute("DELETE FROM draft_analysis_snapshots WHERE league_id = ? AND season = ?", (league_id, season))
    db.execute(
        """
        INSERT INTO draft_analysis_snapshots (league_id, season, scoring_format, player_id, rank, tier, adp)
        SELECT ?, ?, r.scoring_format, r.player_id, r.rank, r.tier, r.adp
        FROM rankings r
        WHERE r.ranking_type = 'draft' AND r.season = ? AND r.scoring_format = ?
        """,
        (league_id, season, season, scoring_format),
    )
    db.execute(
        """
        INSERT INTO draft_completions (league_id, season, scoring_format, completed_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT (league_id, season) DO UPDATE SET
            scoring_format = excluded.scoring_format,
            completed_at = excluded.completed_at
        """,
        (league_id, season, scoring_format),
    )
    db.commit()

    return jsonify({"completed": True, "scoring_format": scoring_format})


@post_draft_bp.delete("/complete")
def reopen_draft(league_id):
    """Undo — clears the completion flag and its snapshot, in case it was marked
    complete too early or a pick still needs correcting on the Draft/Grid tabs.
    """
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year
    db.execute("DELETE FROM draft_completions WHERE league_id = ? AND season = ?", (league_id, season))
    db.execute("DELETE FROM draft_analysis_snapshots WHERE league_id = ? AND season = ?", (league_id, season))
    db.commit()
    return "", 204
