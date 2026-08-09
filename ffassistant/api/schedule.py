import datetime

from flask import Blueprint, jsonify, request

from ffassistant.api import get_db

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")

WEEKS = list(range(1, 18))  # weeks 1-17; week 18 isn't a fantasy week
NOTABLE_RANK = 8  # matches draft.js's SOS_NOTABLE_RANK convention for Hard/Easy SOS


def difficulty_for_rank(rank: int, total_teams: int) -> str | None:
    """rank is 1 = highest season win total (toughest opponent). Top/bottom
    NOTABLE_RANK of `total_teams` are notable; everyone else is 'medium' (None).
    """
    if rank <= NOTABLE_RANK:
        return "hard"
    if rank > total_teams - NOTABLE_RANK:
        return "easy"
    return None


@schedule_bp.get("")
def get_schedule():
    """Full weeks 1-17 schedule for every NFL team, with each matchup tagged
    'hard'/'easy' by the opponent's season win total (own_implied_wins) ranked
    against the other 31 teams — same top/bottom-8-of-32 cutoff already used
    for the Hard/Easy SOS tags in the Draft tab, just applied per-week here
    instead of only to the weeks 15-17 playoff stretch.
    """
    db = get_db()
    season = request.args.get("season", type=int) or datetime.date.today().year

    win_total_rows = db.execute(
        "SELECT team, own_implied_wins FROM nfl_team_playoff_sos WHERE season = ?",
        (season,),
    ).fetchall()
    win_totals = {row["team"]: row["own_implied_wins"] for row in win_total_rows}
    ranked_teams = sorted(win_totals, key=lambda t: win_totals[t], reverse=True)
    rank_by_team = {team: i + 1 for i, team in enumerate(ranked_teams)}

    def difficulty(opponent):
        rank = rank_by_team.get(opponent)
        if rank is None:
            return None
        return difficulty_for_rank(rank, len(ranked_teams))

    bye_rows = db.execute(
        "SELECT team, bye_week FROM nfl_team_byes WHERE season = ? ORDER BY team", (season,)
    ).fetchall()
    bye_week_by_team = {row["team"]: row["bye_week"] for row in bye_rows}

    schedule_rows = db.execute(
        "SELECT team, week, opponent, is_home FROM nfl_team_schedule WHERE season = ?",
        (season,),
    ).fetchall()
    matchup_by_team_week = {(row["team"], row["week"]): row for row in schedule_rows}

    teams = []
    for team in sorted(bye_week_by_team):
        weeks = []
        for week in WEEKS:
            if week == bye_week_by_team.get(team):
                weeks.append({"bye": True})
                continue
            row = matchup_by_team_week.get((team, week))
            if row is None:
                weeks.append(None)
                continue
            weeks.append(
                {
                    "opponent": row["opponent"],
                    "is_home": bool(row["is_home"]),
                    "opponent_wins": win_totals.get(row["opponent"]),
                    "difficulty": difficulty(row["opponent"]),
                }
            )
        teams.append({"team": team, "own_implied_wins": win_totals.get(team), "weeks": weeks})

    return jsonify({"season": season, "weeks": WEEKS, "teams": teams})
