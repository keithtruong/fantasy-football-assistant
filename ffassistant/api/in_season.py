import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

in_season_bp = Blueprint("in_season", __name__, url_prefix="/api/leagues")

WEEKLY_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]
ROS_POSITIONS = ["QB", "RB", "WR", "TE"]  # DST/K aren't rest-of-season assets, per CLAUDE.md

AVAILABLE_LIMIT_PER_POSITION = 30


@in_season_bp.get("/<int:league_id>/in_season")
def get_in_season(league_id):
    """Rostered-vs-available view for Keith's own team, grouped by position.

    Both lists sort best-first (lowest rank first); unranked/injured rostered
    players still appear (never dropped), sorted to the bottom since there's no
    rank to sort them by. Available players are shown ungated by whether they'd
    actually be an upgrade.

    Response is keyed by position, plus top-level "waiver_priority", "record",
    "opponent", and "player_news" for Keith's team — all None/empty if not yet
    synced (record/opponent/waiver_priority need a platform resync; player_news
    needs a news sync — see ffassistant.ingest.news).

    view=starters is a different shape entirely (a slot-by-slot lineup, not a
    position-grouped rostered/available list) — see _get_starters.
    """
    db = get_db()
    view = request.args.get("view", "weekly")
    if view not in ("weekly", "ros", "starters"):
        abort(400, description="view must be 'weekly', 'ros', or 'starters'")

    season = request.args.get("season", type=int) or datetime.date.today().year
    week = request.args.get("week", type=int)
    if view in ("weekly", "starters") and week is None:
        abort(400, description=f"week is required for view={view}")

    if view == "starters":
        return _get_starters(db, league_id, season, week)

    positions = WEEKLY_POSITIONS if view == "weekly" else ROS_POSITIONS
    ranking_type = "weekly" if view == "weekly" else "ros"

    # Weekly has no superflex list at all (only reception scoring varies — see
    # ffassistant.api.leagues.derive_reception_scoring); ROS mirrors the draft
    # board's full superflex-aware format instead.
    from ffassistant.api.leagues import derive_reception_scoring, derive_scoring_format

    scoring_format = derive_reception_scoring(db, league_id) if view == "weekly" else derive_scoring_format(db, league_id)

    my_team = db.execute(
        "SELECT team_id, waiver_priority, wins, losses, ties FROM teams WHERE league_id = ? AND is_mine = 1",
        (league_id,),
    ).fetchone()
    if my_team is None:
        abort(400, description="No team is marked as yours in this league yet — set it in League Settings")
    my_team_id = my_team["team_id"]

    rostered_rows = _fetch_rostered(db, my_team_id, ranking_type, season, week, scoring_format)
    available_rows = _fetch_available(db, league_id, ranking_type, season, week, scoring_format)

    result = {}
    for position in positions:
        rostered = [r for r in rostered_rows if r["position"] == position]
        available = [r for r in available_rows if r["position"] == position][:AVAILABLE_LIMIT_PER_POSITION]

        has_unranked_rostered = any(r["rank"] is None for r in rostered)
        ranked_rostered = [r["rank"] for r in rostered if r["rank"] is not None]
        worst_rostered_rank = max(ranked_rostered) if ranked_rostered else None

        for player in available:
            if has_unranked_rostered:
                player["beats_worst_rostered"] = True
            elif worst_rostered_rank is None:
                player["beats_worst_rostered"] = False  # nothing rostered here to compare against
            else:
                player["beats_worst_rostered"] = player["rank"] is not None and player["rank"] < worst_rostered_rank

        result[position] = {"rostered": rostered, "available": available}

    result["waiver_priority"] = my_team["waiver_priority"]
    result["record"] = {"wins": my_team["wins"], "losses": my_team["losses"], "ties": my_team["ties"]}

    # ROS has no week param of its own — fall back to the season's current week
    # (same signal the in-season refresh pipeline uses) to know which matchup to show.
    matchup_week = week
    if matchup_week is None:
        from ffassistant.season import smart_current_week

        matchup_week = smart_current_week(db, season)
    result["opponent"] = _fetch_opponent(db, league_id, season, matchup_week, my_team_id)

    result["player_news"] = _fetch_player_news(db, my_team_id)

    return jsonify(result)


def _get_starters(db, league_id, season, week):
    """Optimal starting lineup for Keith's own team this week — see
    _compute_starters_for_league for the actual computation."""
    result = _compute_starters_for_league(db, league_id, season, week)
    if result is None:
        abort(400, description="No team is marked as yours in this league yet — set it in League Settings")
    return jsonify(result)


def _compute_starters_for_league(db, league_id, season, week):
    """Optimal starting lineup for Keith's own team in one league — see
    ffassistant.starters.compute_starters for the assignment algorithm. Uses the
    same reception-scoring resolution as the Weekly view (the combined FLEX/
    SUPER_FLEX lists vary by scoring format too, independent of whether this
    league actually has those slots).

    Returns None (rather than raising) if no team is marked as Keith's own in
    this league yet, so a cross-league caller (see get_starters_all) can just
    skip it instead of failing the whole request over one unconfigured league.
    """
    from ffassistant.api.leagues import derive_reception_scoring
    from ffassistant.starters import compute_starters

    scoring_format = derive_reception_scoring(db, league_id)

    my_team = db.execute(
        "SELECT team_id FROM teams WHERE league_id = ? AND is_mine = 1", (league_id,)
    ).fetchone()
    if my_team is None:
        return None
    team_id = my_team["team_id"]

    roster_slots = {
        r["slot_name"]: r["slot_count"]
        for r in db.execute("SELECT slot_name, slot_count FROM roster_slots WHERE league_id = ?", (league_id,))
    }

    rows = db.execute(
        """
        SELECT p.player_id, p.full_name, p.position, ps.status,
               r_pos.rank AS rank, r_flex.rank AS flex_rank, r_op.rank AS op_rank
        FROM roster_spots rs
        JOIN players p ON p.player_id = rs.player_id
        LEFT JOIN rankings r_pos ON r_pos.player_id = p.player_id AND r_pos.ranking_type = 'weekly'
              AND r_pos.season = ? AND r_pos.week = ? AND r_pos.scoring_format = ? AND r_pos.list_type IS NULL
        LEFT JOIN rankings r_flex ON r_flex.player_id = p.player_id AND r_flex.ranking_type = 'weekly'
              AND r_flex.season = ? AND r_flex.week = ? AND r_flex.scoring_format = ? AND r_flex.list_type = 'flex'
        LEFT JOIN rankings r_op ON r_op.player_id = p.player_id AND r_op.ranking_type = 'weekly'
              AND r_op.season = ? AND r_op.week = ? AND r_op.scoring_format = ? AND r_op.list_type = 'superflex'
        LEFT JOIN player_status ps ON ps.player_id = p.player_id AND ps.season = ? AND ps.week = ?
        WHERE rs.team_id = ?
        """,
        (
            season, week, scoring_format,
            season, week, scoring_format,
            season, week, scoring_format,
            season, week,
            team_id,
        ),
    ).fetchall()
    players = [dict(r) for r in rows]

    result = compute_starters(roster_slots, players)
    result["scoring_format"] = scoring_format
    return result


# Not league-scoped — every one of Keith's teams across all active leagues at
# once, for the Starters tab's all-leagues view (see CLAUDE.md: the tab shows
# every team side by side rather than gating behind the league selector,
# similar in spirit to Exposure's cross-league scope).
starters_all_bp = Blueprint("starters_all", __name__, url_prefix="/api")


@starters_all_bp.get("/starters_all")
def get_starters_all():
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year
    week = request.args.get("week", type=int)
    if week is None:
        abort(400, description="week is required")

    leagues = db.execute(
        """
        SELECT l.league_id, l.name AS league_name, t.team_name
        FROM leagues l
        JOIN teams t ON t.league_id = l.league_id AND t.is_mine = 1
        WHERE l.active = 1
        ORDER BY l.name
        """
    ).fetchall()

    results = []
    for league in leagues:
        starters = _compute_starters_for_league(db, league["league_id"], season, week)
        if starters is None:
            continue
        results.append(
            {
                "league_id": league["league_id"],
                "league_name": league["league_name"],
                "team_name": league["team_name"],
                **starters,
            }
        )
    return jsonify(results)


def _fetch_opponent(db, league_id, season, week, my_team_id):
    if week is None:
        return None
    row = db.execute(
        """
        SELECT o.team_name, o.wins, o.losses, o.ties
        FROM weekly_matchups wm
        JOIN teams o ON o.team_id = wm.opponent_team_id
        WHERE wm.league_id = ? AND wm.season = ? AND wm.week = ? AND wm.team_id = ?
        """,
        (league_id, season, week, my_team_id),
    ).fetchone()
    if row is None:
        return None
    return {"team_name": row["team_name"], "wins": row["wins"], "losses": row["losses"], "ties": row["ties"]}


def _fetch_player_news(db, team_id):
    """One entry per rostered player who has a digest, with their underlying
    source items as supporting links. The digest (from ffassistant.claude_news,
    synthesized across that player's recent items) is the headline fact; items
    are secondary, for click-through to the original source.
    """
    digest_rows = db.execute(
        """
        SELECT pnd.player_id, p.full_name, pnd.digest
        FROM player_news_digest pnd
        JOIN roster_spots rs ON rs.player_id = pnd.player_id
        JOIN players p ON p.player_id = pnd.player_id
        WHERE rs.team_id = ?
        """,
        (team_id,),
    ).fetchall()

    result = []
    for row in digest_rows:
        item_rows = db.execute(
            "SELECT headline, link, category, published_at FROM player_news "
            "WHERE player_id = ? ORDER BY published_at IS NULL, published_at DESC",
            (row["player_id"],),
        ).fetchall()
        result.append(
            {
                "player_id": row["player_id"],
                "full_name": row["full_name"],
                "digest": row["digest"],
                "items": [dict(r) for r in item_rows],
            }
        )
    return result


def _fetch_rostered(db, team_id, ranking_type, season, week, scoring_format):
    rank_filter, rank_params = _rank_filter(ranking_type, week, scoring_format)
    pos_rank_join, pos_rank_params = _pos_rank_join(ranking_type, season, week, scoring_format)
    rows = db.execute(
        f"""
        SELECT p.player_id, p.full_name, p.position, r.rank, ps.status, pr.pos_rank
        FROM roster_spots rs
        JOIN players p ON p.player_id = rs.player_id
        LEFT JOIN rankings r ON r.player_id = p.player_id
              AND r.ranking_type = ? AND r.season = ? {rank_filter}
        LEFT JOIN player_status ps ON ps.player_id = p.player_id AND ps.season = ? AND ps.week = ?
        {pos_rank_join}
        WHERE rs.team_id = ?
        ORDER BY (r.rank IS NULL) ASC, r.rank ASC
        """,
        (ranking_type, season, *rank_params, season, week, *pos_rank_params, team_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_available(db, league_id, ranking_type, season, week, scoring_format):
    rank_filter, rank_params = _rank_filter(ranking_type, week, scoring_format)
    pos_rank_join, pos_rank_params = _pos_rank_join(ranking_type, season, week, scoring_format)
    rows = db.execute(
        f"""
        SELECT p.player_id, p.full_name, p.position, r.rank, pr.pos_rank
        FROM players p
        JOIN rankings r ON r.player_id = p.player_id
              AND r.ranking_type = ? AND r.season = ? {rank_filter}
        {pos_rank_join}
        WHERE p.player_id NOT IN (
            SELECT rs.player_id FROM roster_spots rs
            JOIN teams t ON t.team_id = rs.team_id
            WHERE t.league_id = ?
        )
        ORDER BY r.rank ASC
        """,
        (ranking_type, season, *rank_params, *pos_rank_params, league_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _rank_filter(ranking_type, week, scoring_format, alias="r"):
    """'ros' rankings never have a week (schema convention, same as 'draft'); only
    'weekly' rows need the week filter. Both need a scoring_format filter, since
    more than one format's rankings can coexist for the same ranking_type/season
    (e.g. weekly's full_ppr/half_ppr/non_ppr, or ROS's four draft-style buckets).
    list_type IS NULL excludes weekly's two combined FLEX/SUPER_FLEX lists (see
    ffassistant.starters), which share this same key space but aren't meant for
    the plain per-position Rostered/Available views here."""
    if ranking_type == "weekly":
        return f"AND {alias}.week = ? AND {alias}.scoring_format = ? AND {alias}.list_type IS NULL", (week, scoring_format)
    return f"AND {alias}.week IS NULL AND {alias}.scoring_format = ? AND {alias}.list_type IS NULL", (scoring_format,)


def _pos_rank_join(ranking_type, season, week, scoring_format):
    """Rank-within-position, computed over the *full* ranked pool for this
    ranking_type/season/week/scoring_format — not just whichever rostered/available
    subset is being queried, so e.g. a QB's pos_rank reflects the whole league's
    QB order under that same scoring format."""
    rank_filter, rank_params = _rank_filter(ranking_type, week, scoring_format, alias="r2")
    sql = f"""
        LEFT JOIN (
            SELECT r2.player_id,
                   RANK() OVER (PARTITION BY p2.position ORDER BY r2.rank ASC) AS pos_rank
            FROM rankings r2
            JOIN players p2 ON p2.player_id = r2.player_id
            WHERE r2.ranking_type = ? AND r2.season = ? AND r2.rank IS NOT NULL {rank_filter}
        ) pr ON pr.player_id = p.player_id
    """
    return sql, (ranking_type, season, *rank_params)
