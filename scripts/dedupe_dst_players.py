"""One-time cleanup of duplicate DST (defense/special-teams) player rows.

Each connector names defenses differently ("ATL DST" vs "Atlanta Falcons" vs
"Falcons D/ST" vs bare "Falcons"), and the exact/suffix-normalized matching
pipeline in name_matching.py doesn't bridge those styles for team-style names
the way it does for person names. The result: up to four separate player
rows per real-world defense, which don't disappear from the draft board
together when one of them gets picked.

For each of the 32 teams, this keeps the row with the most `rankings` rows
(i.e. the one actually being kept current by rankings ingestion — ties
broken by having a rankings-provider alias, then lowest player_id) and
merges every other row for that team into it: aliases, draft picks, roster
spots, player status, and manual sleeper/shy-away tags are repointed to the
winner; the losers' own (stale) rankings rows are left behind to be deleted
along with the loser row itself via ON DELETE CASCADE. Also normalizes the
two known team-code drifts on the winner row (Rams' rankings-provider code
"LA" and Washington's "WAS") to the codes nfl_team_byes/nfl_team_playoff_sos
actually use ("LAR", "WSH"), so bye/SOS joins work for those two defenses.

Idempotent: a second run finds one row per team (no duplicates) and does
nothing.

Usage:
    python -m scripts.dedupe_dst_players
"""

import sqlite3

from ffassistant.db import get_connection

# Rankings-provider team-code drift vs. the codes nfl_team_byes/
# nfl_team_playoff_sos use. Applied to the winner row only.
_TEAM_CODE_FIXES = {"LA": "LAR", "WAS": "WSH"}


def _canonical_team_code(raw_team: str) -> str:
    code = raw_team.strip().upper()
    return _TEAM_CODE_FIXES.get(code, code)


def _pick_winner(conn: sqlite3.Connection, player_ids: list[int]) -> int:
    best_id = None
    best_key = None
    for pid in player_ids:
        n_rankings = conn.execute(
            "SELECT COUNT(*) AS c FROM rankings WHERE player_id = ?", (pid,)
        ).fetchone()["c"]
        has_rankings_alias = conn.execute(
            "SELECT 1 FROM player_aliases WHERE player_id = ? AND source = 'rankings_provider' LIMIT 1",
            (pid,),
        ).fetchone() is not None
        # Sort descending on (n_rankings, has_alias), ascending on player_id.
        key = (n_rankings, 1 if has_rankings_alias else 0, -pid)
        if best_key is None or key > best_key:
            best_key = key
            best_id = pid
    return best_id


def _reassign_conflict_safe(conn: sqlite3.Connection, table: str, id_col: str, loser: int, winner: int) -> None:
    """Repoint player_id from loser to winner in `table`, dropping any row
    that would collide with an existing winner row on `table`'s natural key
    (rather than erroring), since a collision just means the winner already
    has an equivalent row. `id_col` is the table's own single-column primary
    key (not player_id itself).
    """
    rows = conn.execute(f"SELECT {id_col} FROM {table} WHERE player_id = ?", (loser,)).fetchall()
    for row in rows:
        row_id = row[id_col]
        try:
            conn.execute(f"UPDATE {table} SET player_id = ? WHERE {id_col} = ?", (winner, row_id))
        except sqlite3.IntegrityError:
            conn.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (row_id,))


def _reassign_player_status(conn: sqlite3.Connection, loser: int, winner: int) -> None:
    """player_status has no single-column id — its primary key is
    (player_id, season, week), so reassignment is handled directly rather
    than through _reassign_conflict_safe.
    """
    rows = conn.execute(
        "SELECT season, week FROM player_status WHERE player_id = ?", (loser,)
    ).fetchall()
    for row in rows:
        try:
            conn.execute(
                "UPDATE player_status SET player_id = ? WHERE player_id = ? AND season = ? AND week = ?",
                (winner, loser, row["season"], row["week"]),
            )
        except sqlite3.IntegrityError:
            conn.execute(
                "DELETE FROM player_status WHERE player_id = ? AND season = ? AND week = ?",
                (loser, row["season"], row["week"]),
            )


def _reassign_manual_tag(conn: sqlite3.Connection, loser: int, winner: int) -> None:
    """player_manual_tags' primary key is player_id itself, so a loser's tag
    only moves over if the winner doesn't already have one — otherwise the
    winner's own tag wins and the loser's is dropped.
    """
    loser_tag = conn.execute("SELECT tag FROM player_manual_tags WHERE player_id = ?", (loser,)).fetchone()
    if loser_tag is None:
        return
    winner_has_tag = conn.execute(
        "SELECT 1 FROM player_manual_tags WHERE player_id = ?", (winner,)
    ).fetchone() is not None
    if winner_has_tag:
        conn.execute("DELETE FROM player_manual_tags WHERE player_id = ?", (loser,))
    else:
        conn.execute(
            "INSERT INTO player_manual_tags (player_id, tag) VALUES (?, ?)", (winner, loser_tag["tag"])
        )
        conn.execute("DELETE FROM player_manual_tags WHERE player_id = ?", (loser,))


def dedupe_dst_players(conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_connection()

    dst_players = conn.execute(
        "SELECT player_id, full_name, nfl_team FROM players WHERE position = 'DST'"
    ).fetchall()

    groups: dict[str, list[int]] = {}
    for row in dst_players:
        if not row["nfl_team"]:
            continue
        groups.setdefault(_canonical_team_code(row["nfl_team"]), []).append(row["player_id"])

    teams_with_duplicates = 0
    duplicates_deleted = 0
    winners_by_team = {}

    for team_code, player_ids in groups.items():
        winner = _pick_winner(conn, player_ids)
        winners_by_team[team_code] = winner

        # Normalize the winner's team code (fixes the Rams/Washington drift).
        conn.execute("UPDATE players SET nfl_team = ? WHERE player_id = ?", (team_code, winner))

        losers = [pid for pid in player_ids if pid != winner]
        if not losers:
            continue
        teams_with_duplicates += 1

        for loser in losers:
            _reassign_conflict_safe(conn, "player_aliases", "alias_id", loser, winner)
            _reassign_conflict_safe(conn, "roster_spots", "roster_spot_id", loser, winner)
            _reassign_player_status(conn, loser, winner)
            _reassign_manual_tag(conn, loser, winner)
            conn.execute("UPDATE draft_picks SET player_id = ? WHERE player_id = ?", (winner, loser))
            conn.execute("UPDATE waiver_suggestions SET player_id = ? WHERE player_id = ?", (winner, loser))
            # Any rankings rows left on the loser are stale duplicates of a
            # naming-convention change — deleting the loser row cascades
            # them away rather than migrating them onto the winner.
            conn.execute("DELETE FROM players WHERE player_id = ?", (loser,))
            duplicates_deleted += 1

    conn.commit()
    return {
        "teams_processed": len(groups),
        "teams_with_duplicates": teams_with_duplicates,
        "duplicates_deleted": duplicates_deleted,
        "winners_by_team": winners_by_team,
    }


if __name__ == "__main__":
    result = dedupe_dst_players()
    print(f"Teams processed: {result['teams_processed']}")
    print(f"Teams that had duplicates: {result['teams_with_duplicates']}")
    print(f"Duplicate rows removed: {result['duplicates_deleted']}")
