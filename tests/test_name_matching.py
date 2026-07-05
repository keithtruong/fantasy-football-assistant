import sqlite3
import unittest
from pathlib import Path

from ffassistant.name_matching import list_unresolved, match_player, normalize, resolve_override

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestNormalize(unittest.TestCase):
    def test_strips_suffix(self):
        self.assertEqual(normalize("Kenneth Walker III"), "kenneth walker")
        self.assertEqual(normalize("Kenneth Walker Jr."), "kenneth walker")

    def test_case_and_punctuation(self):
        self.assertEqual(normalize("A.J. Brown"), "aj brown")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize("Kenneth   Walker"), "kenneth walker")


class TestMatchPlayer(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Kenneth Walker III', 'RB')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (2, 'Justin Jefferson', 'WR')"
        )
        self.conn.commit()

    def test_exact_canonical_match(self):
        player_id = match_player(self.conn, "espn", "Justin Jefferson")
        self.assertEqual(player_id, 2)

    def test_suffix_normalized_match(self):
        # Rankings feed drops the "III" that the canonical name carries.
        player_id = match_player(self.conn, "rankings_provider", "Kenneth Walker")
        self.assertEqual(player_id, 1)

    def test_repeat_lookup_hits_alias_fast_path(self):
        first = match_player(self.conn, "rankings_provider", "Kenneth Walker")
        row_count_before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM player_aliases"
        ).fetchone()["c"]
        second = match_player(self.conn, "rankings_provider", "Kenneth Walker")
        row_count_after = self.conn.execute(
            "SELECT COUNT(*) AS c FROM player_aliases"
        ).fetchone()["c"]
        self.assertEqual(first, second)
        self.assertEqual(row_count_before, row_count_after)  # no duplicate alias row

    def test_unmatched_name_is_queued(self):
        player_id = match_player(self.conn, "sleeper", "Some Rookie Nobody Has Heard Of")
        self.assertIsNone(player_id)
        unresolved = list_unresolved(self.conn, source="sleeper")
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["raw_name"], "Some Rookie Nobody Has Heard Of")

    def test_manual_override_resolves_and_clears_queue(self):
        match_player(self.conn, "yahoo", "Hendrix Xtreme")  # queues as unresolved
        resolve_override(self.conn, "yahoo", "Hendrix Xtreme", player_id=2)

        self.assertEqual(list_unresolved(self.conn, source="yahoo"), [])
        # Next lookup hits the alias exact-match path.
        self.assertEqual(match_player(self.conn, "yahoo", "Hendrix Xtreme"), 2)

    def test_ambiguous_normalized_match_is_not_guessed(self):
        # Two different real players who happen to normalize identically.
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (3, 'Mike Williams', 'WR')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (4, 'Mike Williams', 'WR')"
        )
        self.conn.commit()
        player_id = match_player(self.conn, "espn", "Mike Williams")
        self.assertIsNone(player_id)


if __name__ == "__main__":
    unittest.main()
