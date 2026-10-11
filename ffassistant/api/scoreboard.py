import datetime
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

scoreboard_bp = Blueprint("scoreboard", __name__, url_prefix="/api")


def _fetch_live_matchup(league: dict, season: int, week: int) -> dict | None:
    """Dispatches to the league's platform connector. Runs on a worker thread,
    so it gets everything it needs passed in — no DB access from here."""
    platform = league["platform"]
    if platform == "espn":
        from ffassistant.connectors import espn

        return espn.get_live_matchup(int(league["platform_league_id"]), season, week, league["platform_team_id"])
    if platform == "yahoo":
        from ffassistant.connectors import yahoo

        # Read-only token use: the session opened in _prepare_platform_connections
        # already refreshed and saved it, and parallel writes to the file collide.
        return yahoo.get_live_matchup(league["platform_league_id"], week, league["platform_team_id"], store_token=False)
    if platform == "sleeper":
        from ffassistant.connectors import sleeper

        return sleeper.get_live_matchup(
            league["platform_league_id"], season, week, league["platform_team_id"], league["reception_scoring"]
        )
    raise ValueError(f"no live scoreboard for platform {platform!r}")


def _prepare_platform_connections(leagues: list[dict]) -> None:
    """Shared setup done once on the request thread before leagues are
    fetched in parallel — both of these broke live when left to the threads:

    - The connectors import their platform libraries lazily, inside each
      call, and several first imports racing let a thread see a
      half-initialized module ("module 'requests' has no attribute 'get'",
      "cannot import name 'OAuth2'").
    - Every Yahoo league opens its own OAuth session from .yahoo_oauth.json,
      and yahoo_oauth rewrites that file on every session open (not only on
      refresh). Four at once means one can read it mid-write ("Expecting
      value: line 1 column 1"). Opening one saving session here refreshes the
      token if needed; the threads then open theirs with store_token=False.

    Failures are swallowed: a missing library or a bad Yahoo token is left
    for that league's own fetch to report on its card.
    """
    for module in ("requests", "objectpath", "espn_api.football", "yahoo_oauth", "yahoo_fantasy_api"):
        try:
            __import__(module)
        except ImportError:
            pass
    if any(lg["platform"] == "yahoo" for lg in leagues):
        try:
            from ffassistant.connectors.yahoo import _connect_game

            _connect_game()
        except Exception:
            pass


@scoreboard_bp.get("/scoreboard")
def get_scoreboard():
    """Keith's matchup in every active platform league, live: each side's
    score, original projection, live projection, and which starters are on
    the field right now (see ffassistant.scoreboard).

    Fetched fresh from each platform on every request and never written to
    the database. Leagues are fetched in parallel; one league failing (an
    expired ESPN cookie, a platform blip) comes back as that league's own
    `error` instead of failing the whole board, same as the in-season
    refresh. A manual league has no API to read from, so it's left off.
    """
    from ffassistant.api.leagues import derive_reception_scoring
    from ffassistant.connectors.espn import get_nfl_scoreboard
    from ffassistant.scoreboard import build_side, parse_nfl_games

    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year
    week = request.args.get("week", type=int)
    if week is None:
        abort(400, description="week is required")

    rows = db.execute(
        """
        SELECT l.league_id, l.name AS league_name, l.platform, l.platform_league_id,
               t.platform_team_id
        FROM leagues l
        JOIN teams t ON t.league_id = l.league_id AND t.is_mine = 1
        WHERE l.active = 1 AND l.platform != 'manual' AND l.platform_league_id IS NOT NULL
        ORDER BY l.name
        """
    ).fetchall()
    leagues = [{**dict(r), "reception_scoring": derive_reception_scoring(db, r["league_id"])} for r in rows]

    team_names = {
        (r["league_id"], r["platform_team_id"]): r["team_name"]
        for r in db.execute(
            f"SELECT league_id, platform_team_id, team_name FROM teams WHERE league_id IN "
            f"({', '.join('?' for _ in leagues) or 'NULL'})",
            [lg["league_id"] for lg in leagues],
        )
    }

    _prepare_platform_connections(leagues)

    def fetch(league):
        try:
            return _fetch_live_matchup(league, season, week), None
        except Exception as e:  # one league's failure shouldn't sink the board
            return None, str(e) or type(e).__name__

    with ThreadPoolExecutor(max_workers=max(1, len(leagues))) as pool:
        nfl_future = pool.submit(get_nfl_scoreboard, season, week)
        results = list(pool.map(fetch, leagues))
        try:
            games = parse_nfl_games(nfl_future.result())
            games_error = None
        except Exception as e:
            games, games_error = {}, str(e) or type(e).__name__

    def side_payload(league_id, side):
        if side is None:
            return None
        built = build_side(side, games)
        built["team_name"] = team_names.get((league_id, built["platform_team_id"]), "Unknown team")
        return built

    matchups = []
    for league, (live, error) in zip(leagues, results):
        matchups.append(
            {
                "league_id": league["league_id"],
                "league_name": league["league_name"],
                "platform": league["platform"],
                "error": error,
                "no_matchup": live is None and error is None,
                "me": side_payload(league["league_id"], live["me"]) if live else None,
                "opponent": side_payload(league["league_id"], live["opponent"]) if live else None,
            }
        )

    return jsonify(
        {
            "season": season,
            "week": week,
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "games_error": games_error,
            "matchups": matchups,
        }
    )
