import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

wl_bp = Blueprint("wl", __name__, url_prefix="/api/wl")

# Fantasy regular seasons have run 16-18 weeks across 2013-2025 — render an
# open-ended grid up to the max so the current season always has editable
# blank slots to fill in as it goes, matching the Grid tab's convention.
MAX_WEEK = 18
CLOSE_GAME_MARGIN = 6
PLAYOFF_ROUNDS = ("semifinal", "final", "third_place")


def _current_year() -> int:
    return datetime.date.today().year


@wl_bp.get("/league_history")
def get_league_history():
    db = get_db()
    rows = db.execute("SELECT league_history_id, name, active FROM league_history ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@wl_bp.get("/games")
def get_games():
    """One card per league for the year — active leagues always get a card
    (even with zero rows yet, so this season's results have somewhere to go),
    inactive/historical leagues only show up for years they actually played.
    """
    db = get_db()
    year = request.args.get("year", type=int) or _current_year()

    leagues = db.execute(
        """
        SELECT DISTINCT lh.league_history_id, lh.name
        FROM league_history lh
        LEFT JOIN matchups m ON m.league_history_id = lh.league_history_id AND m.season = ?
        LEFT JOIN league_seasons ls ON ls.league_history_id = lh.league_history_id AND ls.season = ?
        WHERE lh.active = 1 OR m.matchup_id IS NOT NULL OR ls.league_season_id IS NOT NULL
        ORDER BY lh.name
        """,
        (year, year),
    ).fetchall()

    result = []
    for league in leagues:
        week_rows = db.execute(
            """
            SELECT week, outcome, points_for, points_against, playoff_round
            FROM matchups WHERE league_history_id = ? AND season = ?
            """,
            (league["league_history_id"], year),
        ).fetchall()
        by_week = {r["week"]: dict(r) for r in week_rows}

        weeks = []
        for wk in range(1, MAX_WEEK + 1):
            row = by_week.get(wk)
            if row is None:
                weeks.append(
                    {"week": wk, "outcome": None, "points_for": None, "points_against": None,
                     "differential": None, "playoff_round": None}
                )
            else:
                weeks.append({**row, "differential": row["points_for"] - row["points_against"]})

        totals = db.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN outcome = 'W' THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN outcome = 'L' THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(CASE WHEN outcome = 'T' THEN 1 ELSE 0 END), 0) AS ties,
                COALESCE(SUM(points_for), 0) AS points_for,
                COALESCE(SUM(points_against), 0) AS points_against
            FROM matchups WHERE league_history_id = ? AND season = ?
            """,
            (league["league_history_id"], year),
        ).fetchone()

        result.append(
            {
                "league_history_id": league["league_history_id"],
                "name": league["name"],
                "weeks": weeks,
                "totals": dict(totals),
            }
        )

    return jsonify(result)


@wl_bp.get("/weekly")
def get_weekly():
    """Net games-above-even per week across every league combined, plus a
    running cumulative total through the season."""
    db = get_db()
    year = request.args.get("year", type=int) or _current_year()

    rows = db.execute(
        """
        SELECT week,
               SUM(CASE WHEN outcome = 'W' THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN outcome = 'L' THEN 1 ELSE 0 END) AS losses,
               SUM(CASE WHEN outcome = 'T' THEN 1 ELSE 0 END) AS ties,
               SUM(points_for) AS points_for,
               SUM(points_against) AS points_against
        FROM matchups WHERE season = ?
        GROUP BY week ORDER BY week
        """,
        (year,),
    ).fetchall()

    weeks = []
    cumulative = 0
    for row in rows:
        net = row["wins"] - row["losses"]
        cumulative += net
        weeks.append(
            {
                "week": row["week"],
                "wins": row["wins"],
                "losses": row["losses"],
                "ties": row["ties"],
                "points_for": row["points_for"],
                "points_against": row["points_against"],
                "net_games_above_even": net,
                "cumulative_net": cumulative,
            }
        )

    return jsonify(weeks)


@wl_bp.get("/leagues")
def get_leagues_view():
    db = get_db()
    year = request.args.get("year", type=int) or _current_year()

    rows = db.execute(
        """
        SELECT lh.league_history_id, lh.name, ls.wins, ls.losses, ls.ties,
               ls.buy_in, ls.max_payout, ls.actual_payout, ls.finish_position
        FROM league_seasons ls
        JOIN league_history lh ON lh.league_history_id = ls.league_history_id
        WHERE ls.season = ?
        ORDER BY lh.name
        """,
        (year,),
    ).fetchall()

    return jsonify([dict(r) for r in rows])


@wl_bp.get("/close_games")
def get_close_games():
    """Fixed threshold (< 6-point margin), not relative/percentage — Keith's
    own number from how he used the legacy sheet."""
    db = get_db()
    year = request.args.get("year", type=int) or _current_year()

    rows = db.execute(
        """
        SELECT lh.name AS league_name, m.week, m.outcome,
               ABS(m.points_for - m.points_against) AS margin
        FROM matchups m
        JOIN league_history lh ON lh.league_history_id = m.league_history_id
        WHERE m.season = ? AND ABS(m.points_for - m.points_against) < ?
        ORDER BY margin ASC
        """,
        (year, CLOSE_GAME_MARGIN),
    ).fetchall()

    return jsonify([dict(r) for r in rows])


@wl_bp.get("/all_time")
def get_all_time():
    """PF/PA are the real gap-fill the legacy 'All Years' sheet never
    populated — summed here from matchups since league_seasons doesn't carry
    them. Win/loss/tie totals, years played, and finish counts come from
    league_seasons (the season-end figures Keith already tracked)."""
    db = get_db()

    season_rows = db.execute(
        """
        SELECT lh.league_history_id, lh.name,
               COALESCE(SUM(ls.wins), 0) AS wins,
               COALESCE(SUM(ls.losses), 0) AS losses,
               COALESCE(SUM(ls.ties), 0) AS ties,
               COUNT(ls.league_season_id) AS years_played,
               SUM(CASE WHEN ls.finish_position = 1 THEN 1 ELSE 0 END) AS firsts,
               SUM(CASE WHEN ls.finish_position = 2 THEN 1 ELSE 0 END) AS seconds,
               SUM(CASE WHEN ls.finish_position = 3 THEN 1 ELSE 0 END) AS thirds,
               COALESCE(SUM(ls.buy_in), 0) AS total_buy_in,
               COALESCE(SUM(ls.actual_payout), 0) AS total_actual_payout
        FROM league_history lh
        LEFT JOIN league_seasons ls ON ls.league_history_id = lh.league_history_id
        GROUP BY lh.league_history_id, lh.name
        ORDER BY lh.name
        """
    ).fetchall()

    pf_pa_rows = db.execute(
        """
        SELECT league_history_id, SUM(points_for) AS points_for, SUM(points_against) AS points_against
        FROM matchups GROUP BY league_history_id
        """
    ).fetchall()
    pf_pa_by_id = {r["league_history_id"]: r for r in pf_pa_rows}

    # Which specific seasons landed each finish, for hover detail on the
    # 1st/2nd/3rd counts — a bare count doesn't say when.
    finish_rows = db.execute(
        """
        SELECT league_history_id, season, finish_position
        FROM league_seasons
        WHERE finish_position IN (1, 2, 3)
        ORDER BY season
        """
    ).fetchall()
    finish_years_by_id = {}
    for r in finish_rows:
        by_position = finish_years_by_id.setdefault(r["league_history_id"], {1: [], 2: [], 3: []})
        by_position[r["finish_position"]].append(r["season"])

    result = []
    for row in season_rows:
        total_games = row["wins"] + row["losses"] + row["ties"]
        pf_pa = pf_pa_by_id.get(row["league_history_id"])
        finish_years = finish_years_by_id.get(row["league_history_id"], {1: [], 2: [], 3: []})
        result.append(
            {
                "league_history_id": row["league_history_id"],
                "name": row["name"],
                "wins": row["wins"],
                "losses": row["losses"],
                "ties": row["ties"],
                "win_pct": row["wins"] / total_games if total_games else None,
                "years_played": row["years_played"],
                "firsts": row["firsts"],
                "seconds": row["seconds"],
                "thirds": row["thirds"],
                "first_years": finish_years[1],
                "second_years": finish_years[2],
                "third_years": finish_years[3],
                "points_for": pf_pa["points_for"] if pf_pa else None,
                "points_against": pf_pa["points_against"] if pf_pa else None,
                "total_buy_in": row["total_buy_in"],
                "total_actual_payout": row["total_actual_payout"],
            }
        )

    return jsonify(result)


@wl_bp.get("/finishes")
def get_finishes():
    """League x year finish-position grid for the All Years tab's history
    table. Years span every season on record through the current year (so an
    active league's in-progress season still gets a column). A league with no
    league_seasons row for a given year (didn't exist yet, or a gap) gets
    `null` in that cell — same as a row that exists but has no recorded
    finish_position — since the client renders both as "no data" alike.
    """
    db = get_db()

    leagues = db.execute("SELECT league_history_id, name FROM league_history ORDER BY name").fetchall()

    season_bounds = db.execute("SELECT MIN(season) AS mn, MAX(season) AS mx FROM league_seasons").fetchone()
    min_year = season_bounds["mn"]
    max_year = max(season_bounds["mx"] or 0, _current_year()) if min_year else _current_year()
    years = list(range(min_year, max_year + 1)) if min_year else []

    finish_rows = db.execute("SELECT league_history_id, season, finish_position FROM league_seasons").fetchall()
    finish_by_league = {}
    for r in finish_rows:
        finish_by_league.setdefault(r["league_history_id"], {})[r["season"]] = r["finish_position"]

    result_leagues = []
    for league in leagues:
        by_year = finish_by_league.get(league["league_history_id"], {})
        result_leagues.append(
            {
                "league_history_id": league["league_history_id"],
                "name": league["name"],
                "finishes": {str(year): by_year.get(year) for year in years},
            }
        )

    return jsonify({"years": years, "leagues": result_leagues})


@wl_bp.put("/matchups")
def put_matchup():
    """Manual entry/edit for a single week's result — the baseline workflow
    (Keith has always filled these in by hand); outcome is derived here from
    the two scores rather than entered separately."""
    db = get_db()
    body = request.get_json(force=True)

    league_history_id = body.get("league_history_id")
    season = body.get("season")
    week = body.get("week")
    points_for = body.get("points_for")
    points_against = body.get("points_against")
    playoff_round = body.get("playoff_round")

    if not league_history_id or not season or not week or points_for is None or points_against is None:
        abort(400, description="league_history_id, season, week, points_for, and points_against are required")
    if playoff_round is not None and playoff_round not in PLAYOFF_ROUNDS:
        abort(400, description=f"playoff_round must be one of {PLAYOFF_ROUNDS} or null")

    if points_for > points_against:
        outcome = "W"
    elif points_for < points_against:
        outcome = "L"
    else:
        outcome = "T"

    db.execute(
        """
        INSERT INTO matchups (league_history_id, season, week, points_for, points_against, outcome, playoff_round)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (league_history_id, season, week) DO UPDATE SET
            points_for = excluded.points_for,
            points_against = excluded.points_against,
            outcome = excluded.outcome,
            playoff_round = excluded.playoff_round
        """,
        (league_history_id, season, week, points_for, points_against, outcome, playoff_round),
    )
    db.commit()

    return jsonify(
        {
            "league_history_id": league_history_id,
            "season": season,
            "week": week,
            "points_for": points_for,
            "points_against": points_against,
            "outcome": outcome,
            "playoff_round": playoff_round,
        }
    )
