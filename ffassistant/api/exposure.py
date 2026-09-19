import datetime

from flask import Blueprint, jsonify

from ffassistant.api import get_db
from ffassistant.season import smart_current_week

exposure_bp = Blueprint("exposure", __name__, url_prefix="/api/exposure")

CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]


def _group_by_player(rows) -> dict:
    """rows: any query result carrying player_id/full_name/position/nfl_team/
    league_name (+ optionally bye_week) per (player, league) pair — collapses
    repeats of the same player across leagues into one entry with a
    'leagues' list and 'league_count', same shape ffassistant.exposure's two
    endpoints both need."""
    players_by_id = {}
    for row in rows:
        entry = players_by_id.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "full_name": row["full_name"],
                "position": row["position"],
                "nfl_team": row["nfl_team"],
                "bye_week": row["bye_week"] if "bye_week" in row.keys() else None,
                "leagues": [],
            },
        )
        entry["leagues"].append(row["league_name"])

    for entry in players_by_id.values():
        entry["league_count"] = len(entry["leagues"])
    return players_by_id


def _bucket_by_position(players_by_id: dict) -> dict:
    """Buckets an already-grouped players_by_id (see _group_by_player) into
    CORE_POSITIONS, best-exposure-first within each bucket."""
    players_by_position = {pos: [] for pos in CORE_POSITIONS}
    for entry in players_by_id.values():
        if entry["position"] in players_by_position:
            players_by_position[entry["position"]].append(entry)
    for pos in players_by_position:
        players_by_position[pos].sort(key=lambda e: (-e["league_count"], e["full_name"]))
    return players_by_position


def _all_nfl_teams(db, season: int) -> set:
    return {row["team"] for row in db.execute("SELECT DISTINCT team FROM nfl_team_byes WHERE season = ?", (season,))}


def _player_summary(entry: dict) -> dict:
    return {
        "player_id": entry["player_id"],
        "full_name": entry["full_name"],
        "position": entry["position"],
        "league_count": entry["league_count"],
        "leagues": entry["leagues"],
    }


def _starters_by_nfl_team(my_starters_by_id: dict, opponent_starters_by_id: dict) -> list[dict]:
    """Every NFL team with at least one starter on either side this week,
    both sides on the same card (rather than two separate team grids Keith
    would have to cross-reference) plus a verdict so the rooting interest is
    a single glance: 'root_for' (only mine), 'root_against' (only an
    opponent's), or 'mixed' (both — genuinely ambivalent, e.g. Keith starts
    a player an opponent also starts in a different league). A team with
    starters on neither side is never returned here — see quiet_nfl_teams.
    """
    sides_by_team: dict[str, dict] = {}
    for entry in my_starters_by_id.values():
        if entry["nfl_team"]:
            sides_by_team.setdefault(entry["nfl_team"], {"mine": [], "opponent": []})["mine"].append(entry)
    for entry in opponent_starters_by_id.values():
        if entry["nfl_team"]:
            sides_by_team.setdefault(entry["nfl_team"], {"mine": [], "opponent": []})["opponent"].append(entry)

    result = []
    for team, sides in sides_by_team.items():
        my_players = sorted(sides["mine"], key=lambda e: (-e["league_count"], e["full_name"]))
        opponent_players = sorted(sides["opponent"], key=lambda e: (-e["league_count"], e["full_name"]))
        my_count = sum(p["league_count"] for p in my_players)
        opponent_count = sum(p["league_count"] for p in opponent_players)
        verdict = "mixed" if (my_count and opponent_count) else ("root_for" if my_count else "root_against")
        result.append(
            {
                "nfl_team": team,
                "verdict": verdict,
                "my_count": my_count,
                "opponent_count": opponent_count,
                "my_players": [_player_summary(p) for p in my_players],
                "opponent_players": [_player_summary(p) for p in opponent_players],
            }
        )
    result.sort(key=lambda t: (-(t["my_count"] + t["opponent_count"]), t["nfl_team"]))
    return result


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

    players_by_id = _group_by_player(player_rows)
    players_by_position = _bucket_by_position(players_by_id)

    nfl_team_groups = {}
    for entry in players_by_id.values():
        if entry["nfl_team"]:
            nfl_team_groups.setdefault(entry["nfl_team"], []).append(entry)

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
    exposed_team_names = {t["nfl_team"] for t in nfl_teams}
    zero_exposure_teams = sorted(_all_nfl_teams(db, season) - exposed_team_names)

    return jsonify(
        {
            "active_league_count": active_league_count,
            "players_by_position": players_by_position,
            "nfl_teams": nfl_teams,
            "zero_exposure_teams": zero_exposure_teams,
        }
    )


@exposure_bp.get("/starters")
def get_starters_exposure():
    """This week's actual set lineups (roster_status = 'starter' — real,
    platform-reported slot assignments, not a computed optimal lineup; see
    roster_spots.roster_status) split into Keith's own starters and the
    combined starters of his current-week opponents across every active
    league — the "who to root for/against" view. No selectors, same
    cross-league design as GET /api/exposure; the week is resolved
    internally via smart_current_week() rather than taken from the client,
    since Exposure has no week picker.

    A Guillotine-style league has no single current-week opponent (no
    weekly_matchups row — see ffassistant.guillotine), so it naturally never
    contributes to opponent_starters_by_position; its own starters still
    count toward my_starters_by_position like any other league.

    quiet_nfl_teams are real NFL teams with zero exposure across BOTH sets
    combined — nobody Keith starts and nobody any current opponent starts,
    so that game has no bearing on any of his matchups this week.
    """
    db = get_db()
    season = datetime.date.today().year
    week = smart_current_week(db, season)

    my_rows = db.execute(
        """
        SELECT p.player_id, p.full_name, p.position, p.nfl_team, l.name AS league_name
        FROM roster_spots rs
        JOIN teams t ON t.team_id = rs.team_id AND t.is_mine = 1
        JOIN leagues l ON l.league_id = t.league_id AND l.active = 1
        JOIN players p ON p.player_id = rs.player_id
        WHERE rs.roster_status = 'starter'
        ORDER BY p.full_name, l.name
        """
    ).fetchall()

    opponent_rows = []
    if week is not None:
        opponent_rows = db.execute(
            """
            SELECT p.player_id, p.full_name, p.position, p.nfl_team, l.name AS league_name
            FROM weekly_matchups wm
            JOIN teams mine ON mine.team_id = wm.team_id AND mine.is_mine = 1
            JOIN leagues l ON l.league_id = wm.league_id AND l.active = 1
            JOIN roster_spots rs ON rs.team_id = wm.opponent_team_id AND rs.roster_status = 'starter'
            JOIN players p ON p.player_id = rs.player_id
            WHERE wm.season = ? AND wm.week = ?
            ORDER BY p.full_name, l.name
            """,
            (season, week),
        ).fetchall()

    my_starters = _group_by_player(my_rows)
    opponent_starters = _group_by_player(opponent_rows)

    exposed_nfl_teams = {e["nfl_team"] for e in my_starters.values() if e["nfl_team"]} | {
        e["nfl_team"] for e in opponent_starters.values() if e["nfl_team"]
    }
    quiet_nfl_teams = sorted(_all_nfl_teams(db, season) - exposed_nfl_teams)

    return jsonify(
        {
            "week": week,
            "my_starters_by_position": _bucket_by_position(my_starters),
            "opponent_starters_by_position": _bucket_by_position(opponent_starters),
            "starters_by_nfl_team": _starters_by_nfl_team(my_starters, opponent_starters),
            "quiet_nfl_teams": quiet_nfl_teams,
        }
    )
