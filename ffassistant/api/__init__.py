"""Local Flask API serving the SQLite data to the draft tool's frontend.

Read/write within this app is limited to this project's own database — never a
platform. Nothing here calls ESPN/Yahoo/Sleeper write endpoints (see CLAUDE.md's
advisory-only scope boundary).
"""

from pathlib import Path

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from ffassistant.db import SCHEMA_PATH, _migrate, get_connection

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


def get_db():
    if "db" not in g:
        g.db = get_connection()
    return g.db


def _apply_pending_migrations() -> None:
    # Applies any pending schema.sql / _migrate() changes to the db file —
    # without this, a schema change only takes effect once someone remembers to
    # run scripts/init_db.py by hand, and every route fails with a missing-column
    # error until then (see the points_for teams-table incident). Goes through
    # this module's own get_connection (rather than db.init_db(), which always
    # targets the default DB_PATH) so tests that patch get_connection to an
    # isolated db still migrate that db, not the real one.
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def create_app() -> Flask:
    _apply_pending_migrations()

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # abort(status, description=...) otherwise renders an HTML error page —
        # the frontend expects a JSON body with a "description" field.
        return jsonify({"description": e.description}), e.code

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    from ffassistant.api.draft_picks import draft_picks_bp
    from ffassistant.api.exposure import exposure_bp
    from ffassistant.api.in_season import in_season_bp, starters_all_bp
    from ffassistant.api.leagues import leagues_bp
    from ffassistant.api.news import news_bp
    from ffassistant.api.players import players_bp
    from ffassistant.api.post_draft import post_draft_bp
    from ffassistant.api.rankings import rankings_admin_bp, rankings_bp
    from ffassistant.api.refresh import refresh_bp
    from ffassistant.api.schedule import schedule_bp
    from ffassistant.api.season import season_bp
    from ffassistant.api.wl import wl_bp

    app.register_blueprint(leagues_bp)
    app.register_blueprint(rankings_bp)
    app.register_blueprint(rankings_admin_bp)
    app.register_blueprint(draft_picks_bp)
    app.register_blueprint(post_draft_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(in_season_bp)
    app.register_blueprint(starters_all_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(refresh_bp)
    app.register_blueprint(exposure_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(season_bp)
    app.register_blueprint(wl_bp)

    return app
