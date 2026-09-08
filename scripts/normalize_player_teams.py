"""Rerunnable normalization of players.nfl_team onto canonical team codes.

Historically each connector wrote whatever abbreviation its platform used
(ESPN "WSH", Yahoo title-case "Was", Sleeper / rankings provider "WAS" and
"LA"), and nfl_team was set once at player creation and never revisited — so
the same NFL team accumulated several spellings in players.nfl_team and
stopped joining to nfl_team_byes / _playoff_sos / _schedule / _implied_totals.
That surfaced on the Exposure page as a Commanders player showing up under a
"WAS" bucket while "WSH" was listed as having no exposure.

The ingest path now normalizes on write via ffassistant.nfl_teams; this
script fixes the rows written before that. Idempotent — a second run finds
every code already canonical and changes nothing.

Usage:
    python -m scripts.normalize_player_teams
"""

import sqlite3

from ffassistant.db import get_connection
from ffassistant.nfl_teams import canonical_team_code


def normalize_player_teams(conn: sqlite3.Connection | None = None) -> dict:
    """Rewrite players.nfl_team through canonical_team_code().

    Returns {"recoded": int, "cleared": int} — `recoded` counts rows moved to
    a different team code, `cleared` counts non-team junk values ("None", "FA")
    set back to NULL.
    """
    conn = conn or get_connection()
    rows = conn.execute("SELECT player_id, nfl_team FROM players").fetchall()

    recoded = 0
    cleared = 0
    for row in rows:
        canonical = canonical_team_code(row["nfl_team"])
        if canonical == row["nfl_team"]:
            continue
        conn.execute(
            "UPDATE players SET nfl_team = ? WHERE player_id = ?", (canonical, row["player_id"])
        )
        if canonical is None:
            cleared += 1
        else:
            recoded += 1

    conn.commit()
    return {"recoded": recoded, "cleared": cleared}


if __name__ == "__main__":
    result = normalize_player_teams()
    print(
        f"Re-coded {result['recoded']} players onto canonical team codes; "
        f"cleared {result['cleared']} non-team values to NULL."
    )
