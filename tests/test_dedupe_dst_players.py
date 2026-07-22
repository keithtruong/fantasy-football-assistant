import sqlite3
import unittest
from pathlib import Path

from scripts.dedupe_dst_players import dedupe_dst_players

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestDedupeDstPlayers(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        # Three rows for one real-world defense: the rankings-provider row
        # (winner, has current rankings) plus two connector-style dupes.
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (?, ?, 'DST', ?)",
            [
                (1, "ATL DST", "ATL"),
                (2, "Atlanta Falcons", "ATL"),
                (3, "Falcons D/ST", "ATL"),
            ],
        )
        self.conn.executemany(
            "INSERT INTO rankings (player_id, ranking_type, season, rank) VALUES (?, 'draft', 2026, 30)",
            [(1,), (1,), (1,), (2,)],
        )
        self.conn.executemany(
            "INSERT INTO player_aliases (player_id, source, alias_name) VALUES (?, ?, ?)",
            [
                (1, "rankings_provider", "ATL DST"),
                (2, "sleeper", "Atlanta Falcons"),
                (3, "espn", "Falcons D/ST"),
            ],
        )
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 10)"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name) VALUES (1, 1, 'My Team')"
        )
        self.conn.execute(
            "INSERT INTO draft_picks (draft_pick_id, league_id, season, round, pick_number, team_id, player_id) "
            "VALUES (1, 1, 2026, 12, 120, 1, 3)"  # drafted the ESPN-named dupe
        )
        self.conn.execute(
            "INSERT INTO player_manual_tags (player_id, tag) VALUES (2, 'shy_away')"
        )
        self.conn.commit()

    def test_merges_duplicates_into_the_rankings_backed_row(self):
        result = dedupe_dst_players(conn=self.conn)

        self.assertEqual(result["teams_with_duplicates"], 1)
        self.assertEqual(result["duplicates_deleted"], 2)

        remaining = self.conn.execute("SELECT player_id, full_name FROM players").fetchall()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["player_id"], 1)
        self.assertEqual(remaining[0]["full_name"], "ATL DST")

    def test_draft_pick_repointed_to_winner_so_it_disappears_everywhere(self):
        dedupe_dst_players(conn=self.conn)

        pick = self.conn.execute("SELECT player_id FROM draft_picks WHERE draft_pick_id = 1").fetchone()
        self.assertEqual(pick["player_id"], 1)

    def test_manual_tag_migrated_to_winner(self):
        dedupe_dst_players(conn=self.conn)

        tags = self.conn.execute("SELECT player_id, tag FROM player_manual_tags").fetchall()
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["player_id"], 1)
        self.assertEqual(tags[0]["tag"], "shy_away")

    def test_stale_loser_rankings_are_dropped_not_migrated(self):
        dedupe_dst_players(conn=self.conn)

        count = self.conn.execute("SELECT COUNT(*) AS c FROM rankings WHERE player_id = 1").fetchone()["c"]
        self.assertEqual(count, 3)  # only the winner's original 3 rows remain

    def test_team_code_drift_is_normalized_on_the_winner(self):
        self.conn.execute("INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (10, 'LA DST', 'DST', 'LA')")
        self.conn.execute("INSERT INTO rankings (player_id, ranking_type, season, rank) VALUES (10, 'draft', 2026, 31)")
        self.conn.commit()

        dedupe_dst_players(conn=self.conn)

        row = self.conn.execute("SELECT nfl_team FROM players WHERE player_id = 10").fetchone()
        self.assertEqual(row["nfl_team"], "LAR")

    def test_conflicting_roster_spot_is_dropped_not_errored(self):
        self.conn.execute(
            "INSERT INTO roster_spots (team_id, player_id, acquired_via) VALUES (1, 1, 'draft')"
        )
        self.conn.execute(
            "INSERT INTO roster_spots (team_id, player_id, acquired_via) VALUES (1, 2, 'draft')"
        )
        self.conn.commit()

        dedupe_dst_players(conn=self.conn)  # must not raise

        spots = self.conn.execute("SELECT team_id, player_id FROM roster_spots").fetchall()
        self.assertEqual(len(spots), 1)
        self.assertEqual(spots[0]["player_id"], 1)

    def test_rerun_is_idempotent(self):
        dedupe_dst_players(conn=self.conn)
        second = dedupe_dst_players(conn=self.conn)

        self.assertEqual(second["teams_with_duplicates"], 0)
        self.assertEqual(second["duplicates_deleted"], 0)
        remaining = self.conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
        self.assertEqual(remaining, 1)


if __name__ == "__main__":
    unittest.main()
