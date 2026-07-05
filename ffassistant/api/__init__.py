"""Local Flask API serving the SQLite data to the draft tool's frontend.

Read/write within this app is limited to this project's own database — never a
platform. Nothing here calls ESPN/Yahoo/Sleeper write endpoints (see CLAUDE.md's
advisory-only scope boundary).
"""

from pathlib import Path

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from ffassistant.db import get_connection

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


def get_db():
    if "db" not in g:
        g.db = get_connection()
    return g.db


def create_app() -> Flask:
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
    from ffassistant.api.leagues import leagues_bp
    from ffassistant.api.players import players_bp
    from ffassistant.api.rankings import rankings_bp

    app.register_blueprint(leagues_bp)
    app.register_blueprint(rankings_bp)
    app.register_blueprint(draft_picks_bp)
    app.register_blueprint(players_bp)

    return app
