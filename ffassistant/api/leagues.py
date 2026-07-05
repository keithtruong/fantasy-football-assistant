import datetime

from flask import Blueprint, abort, jsonify, request

from ffassistant.api import get_db

leagues_bp = Blueprint("leagues", __name__, url_prefix="/api/leagues")

_PLATFORMS = ("sleeper", "espn", "yahoo")


@leagues_bp.get("")
def list_leagues():
    db = get_db()
    include_inactive = request.args.get("include_inactive") == "1"
    where_clause = "" if include_inactive else "WHERE l.active = 1"
    rows = db.execute(
        f"""
        SELECT l.league_id, l.name, l.platform, l.platform_league_id, l.team_count, l.active,
               t.team_id AS my_team_id, t.team_name AS my_team_name
        FROM leagues l
        LEFT JOIN teams t ON t.league_id = l.league_id AND t.is_mine = 1
        {where_clause}
        ORDER BY l.name
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@leagues_bp.post("")
def create_league():
    """Creates a league record and immediately syncs it from its platform —
    this is what stands in for a real connector-onboarding flow so a league
    can be added without hand-running SQL/scripts.

    Re-submitting the same platform + platform_league_id is treated as a
    re-sync of the existing league rather than creating a duplicate — this
    matters because a slow/ambiguous UI response (see: this actually happening)
    invites exactly that double-submit.
    """
    db = get_db()
    body = request.get_json(force=True)
    name = body.get("name")
    platform = body.get("platform")
    platform_league_id = body.get("platform_league_id")
    season = int(body.get("season") or datetime.date.today().year)

    if not name or platform not in _PLATFORMS or not platform_league_id:
        abort(400, description=f"name, platform ({'/'.join(_PLATFORMS)}), and platform_league_id are required")

    existing = db.execute(
        "SELECT league_id FROM leagues WHERE platform = ? AND platform_league_id = ?",
        (platform, str(platform_league_id)),
    ).fetchone()

    if existing:
        league_id = existing["league_id"]
        db.execute("UPDATE leagues SET name = ? WHERE league_id = ?", (name, league_id))
        db.commit()
    else:
        row = db.execute(
            "INSERT INTO leagues (name, platform, platform_league_id, team_count, active) "
            "VALUES (?, ?, ?, 0, 1) RETURNING league_id",
            (name, platform, str(platform_league_id)),
        ).fetchone()
        league_id = row["league_id"]
        db.commit()

    try:
        _sync_from_platform(db, league_id, platform, platform_league_id, season)
    except Exception as e:
        if not existing:
            # Don't leave a broken, un-synced league row behind for a failed add.
            db.execute("DELETE FROM leagues WHERE league_id = ?", (league_id,))
            db.commit()
        abort(502, description=f"Sync failed{'' if existing else ', league not created'}: {e}")

    return jsonify({"league_id": league_id, "already_existed": bool(existing)}), 200 if existing else 201


@leagues_bp.put("/<int:league_id>")
def update_league(league_id):
    db = get_db()
    body = request.get_json(force=True)
    fields = {}
    if "name" in body:
        fields["name"] = body["name"]
    if "active" in body:
        fields["active"] = 1 if body["active"] else 0
    if not fields:
        abort(400, description="No editable fields provided")

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    result = db.execute(f"UPDATE leagues SET {set_clause} WHERE league_id = ?", (*fields.values(), league_id))
    if result.rowcount == 0:
        abort(404, description="League not found")
    db.commit()
    return jsonify({"league_id": league_id, **fields})


@leagues_bp.delete("/<int:league_id>")
def delete_league(league_id):
    """Cascades to teams, roster_slots, league_scoring, draft_picks, etc. (see schema.sql)."""
    db = get_db()
    result = db.execute("DELETE FROM leagues WHERE league_id = ?", (league_id,))
    if result.rowcount == 0:
        abort(404, description="League not found")
    db.commit()
    return "", 204


@leagues_bp.post("/<int:league_id>/sync")
def resync_league(league_id):
    db = get_db()
    league = db.execute(
        "SELECT platform, platform_league_id FROM leagues WHERE league_id = ?", (league_id,)
    ).fetchone()
    if league is None:
        abort(404, description="League not found")

    body = request.get_json(silent=True) or {}
    season = int(body.get("season") or datetime.date.today().year)

    try:
        _sync_from_platform(db, league_id, league["platform"], league["platform_league_id"], season)
    except Exception as e:
        abort(502, description=f"Sync failed: {e}")

    return jsonify({"league_id": league_id})


def _sync_from_platform(db, league_id, platform, platform_league_id, season):
    if platform == "sleeper":
        from ffassistant.ingest import sleeper as sleeper_ingest

        sleeper_ingest.sync_league(db, league_id, str(platform_league_id))
    elif platform == "espn":
        from ffassistant.ingest import espn as espn_ingest

        try:
            espn_numeric_id = int(platform_league_id)
        except ValueError:
            raise ValueError(
                f"ESPN league ID must be numeric (e.g. 360508, from the leagueId= URL param) — got {platform_league_id!r}"
            )
        espn_ingest.sync_league(db, league_id, espn_numeric_id, year=season)
    elif platform == "yahoo":
        from ffassistant.ingest import yahoo as yahoo_ingest

        yahoo_ingest.sync_league(db, league_id, str(platform_league_id), season=season)
    else:
        raise ValueError(f"Unknown platform: {platform}")

    team_count = db.execute("SELECT COUNT(*) AS c FROM teams WHERE league_id = ?", (league_id,)).fetchone()["c"]
    db.execute("UPDATE leagues SET team_count = ? WHERE league_id = ?", (team_count, league_id))
    db.commit()


@leagues_bp.get("/<int:league_id>/settings")
def get_settings(league_id):
    db = get_db()
    roster_slots = db.execute(
        "SELECT slot_name, slot_count FROM roster_slots WHERE league_id = ? ORDER BY slot_name",
        (league_id,),
    ).fetchall()
    scoring = db.execute(
        "SELECT stat_key, points FROM league_scoring WHERE league_id = ? ORDER BY stat_key",
        (league_id,),
    ).fetchall()
    return jsonify(
        {
            "roster_slots": [dict(r) for r in roster_slots],
            "scoring": [dict(r) for r in scoring],
        }
    )


@leagues_bp.get("/<int:league_id>/teams")
def get_teams(league_id):
    """Teams with their roster-in-progress, derived from draft_picks (not stored separately)."""
    db = get_db()
    season = _current_season(db, league_id)

    rows = db.execute(
        """
        SELECT t.team_id, t.team_name, t.is_mine, t.draft_position,
               dp.pick_number, p.player_id, p.full_name, p.position
        FROM teams t
        LEFT JOIN draft_picks dp ON dp.team_id = t.team_id AND dp.season = ?
        LEFT JOIN players p ON p.player_id = dp.player_id
        WHERE t.league_id = ?
        ORDER BY t.draft_position, dp.pick_number
        """,
        (season, league_id),
    ).fetchall()

    teams_by_id = {}
    for row in rows:
        team = teams_by_id.setdefault(
            row["team_id"],
            {
                "team_id": row["team_id"],
                "team_name": row["team_name"],
                "is_mine": bool(row["is_mine"]),
                "draft_position": row["draft_position"],
                "roster": [],
            },
        )
        if row["player_id"] is not None:
            team["roster"].append(
                {
                    "player_id": row["player_id"],
                    "full_name": row["full_name"],
                    "position": row["position"],
                    "pick_number": row["pick_number"],
                }
            )

    return jsonify(list(teams_by_id.values()))


@leagues_bp.put("/<int:league_id>/teams/<int:team_id>")
def update_team(league_id, team_id):
    db = get_db()
    body = request.get_json(force=True)
    fields = {}
    if "draft_position" in body:
        fields["draft_position"] = body["draft_position"]
    if "is_mine" in body:
        if body["is_mine"]:
            # Only one team per league can be "mine".
            db.execute("UPDATE teams SET is_mine = 0 WHERE league_id = ?", (league_id,))
        fields["is_mine"] = 1 if body["is_mine"] else 0
    if not fields:
        abort(400, description="No editable fields provided")

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    result = db.execute(
        f"UPDATE teams SET {set_clause} WHERE team_id = ? AND league_id = ?",
        (*fields.values(), team_id, league_id),
    )
    if result.rowcount == 0:
        abort(404, description="Team not found")
    db.commit()
    return jsonify({"team_id": team_id, **fields})


def _current_season(db, league_id) -> int:
    """The draft-in-progress season is whichever season already has picks, or this year."""
    row = db.execute(
        "SELECT MAX(season) AS season FROM draft_picks WHERE league_id = ?", (league_id,)
    ).fetchone()
    return row["season"] if row and row["season"] is not None else datetime.date.today().year
