import datetime

from flask import Blueprint, jsonify

from ffassistant.api import get_db

exposure_bp = Blueprint("exposure", __name__, url_prefix="/api/exposure")

CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]


@exposure_bp.get("")
def get_exposure():
    """Cross-league concentration for Keith's own teams only. Always current
    roster state (roster_spots is a live snapshot, not season-scoped) — no
    league or season selector, per CLAUDE.md's Exposure section design.
    """
    db = get_db()
    season = datetime.date.today().year

    active_league_count = db.execute(
        "SELECT COUNT(*) AS c FROM leagues WHERE active = 1"
    ).fetchone()["c"]

    player_rows = db.execute(
        """
        SELECT p.player_id, p.full_name, p.position, p.nfl_team, l.name AS league_name,
               byes.bye_week
        FROM roster_spots rs
        JOIN teams t ON t.team_id = rs.team_id AND t.is_mine = 1
        JOIN leagues l ON l.league_id = t.league_id AND l.active = 1
        JOIN players p ON p.player_id = rs.player_id
        LEFT JOIN nfl_team_byes byes ON byes.team = p.nfl_team AND byes.season = ?
        ORDER BY p.full_name, l.name
        """,
        (season,),
    ).fetchall()

    players_by_id = {}
    for row in player_rows:
        entry = players_by_id.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "full_name": row["full_name"],
                "position": row["position"],
                "nfl_team": row["nfl_team"],
                "bye_week": row["bye_week"],
                "leagues": [],
            },
        )
        entry["leagues"].append(row["league_name"])

    for entry in players_by_id.values():
        entry["league_count"] = len(entry["leagues"])

    players_by_position = {pos: [] for pos in CORE_POSITIONS}
    nfl_team_groups = {}
    for entry in players_by_id.values():
        if entry["position"] in players_by_position:
            players_by_position[entry["position"]].append(entry)
        if entry["nfl_team"]:
            nfl_team_groups.setdefault(entry["nfl_team"], []).append(entry)

    for pos in players_by_position:
        players_by_position[pos].sort(key=lambda e: (-e["league_count"], e["full_name"]))

    nfl_teams = []
    for team, players in nfl_team_groups.items():
        players_sorted = sorted(players, key=lambda e: (-e["league_count"], e["full_name"]))
        nfl_teams.append(
            {
                "nfl_team": team,
                "bye_week": players_sorted[0]["bye_week"],
                "roster_spot_count": sum(p["league_count"] for p in players_sorted),
                "unique_player_count": len(players_sorted),
                "players": [
                    {
                        "player_id": p["player_id"],
                        "full_name": p["full_name"],
                        "position": p["position"],
                        "league_count": p["league_count"],
                    }
                    for p in players_sorted
                ],
            }
        )
    nfl_teams.sort(key=lambda s: (-s["roster_spot_count"], s["nfl_team"]))

    # "Teams to not bother watching" — every real NFL team for the season,
    # minus the ones with at least one rostered player above.
    all_nfl_teams = db.execute(
        "SELECT DISTINCT team FROM nfl_team_byes WHERE season = ? ORDER BY team", (season,)
    ).fetchall()
    exposed_team_names = {t["nfl_team"] for t in nfl_teams}
    zero_exposure_teams = [row["team"] for row in all_nfl_teams if row["team"] not in exposed_team_names]

    return jsonify(
        {
            "active_league_count": active_league_count,
            "players_by_position": players_by_position,
            "nfl_teams": nfl_teams,
            "zero_exposure_teams": zero_exposure_teams,
        }
    )
