import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_manual_calls import MANUAL_NOTES_SOURCE, import_manual_calls
from ffassistant.name_matching import list_unresolved

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


NOTES_MD = """\
# Notes

## AFC North

**Ravens**
- Zay Flowers — SLEEPER — ~1:33:43 — "Low-key star," improving efficiency every year.
- Derrick Henry — SHY-AWAY — ~1:24:34 — Capped ceiling.
- Harold Fannin Jr. (TE) — mild SLEEPER — ~1:01:30 — Projected near team-leading targets.

**Bengals**
- Trey McBride — mixed/SLEEPER-leaning — ~2:19:38 — Elite target share but murky outlook.
- Travis Hunter — split opinion — ~1:35 — Two hosts below market, one bullish.
- Some Rookie Nobody Has Heard Of — SLEEPER — ~10:00 — Buy-low target.
"""


class TestImportManualCalls(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Zay Flowers', 'WR')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (2, 'Derrick Henry', 'RB')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (3, 'Harold Fannin Jr.', 'TE')"
        )
        self.conn.commit()

    def _write_notes(self, tmp: str) -> Path:
        path = Path(tmp) / "notes.md"
        path.write_text(NOTES_MD, encoding="utf-8")
        return path

    def test_tags_clear_verdict_players(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = import_manual_calls(self._write_notes(tmp), conn=self.conn)

        self.assertEqual(result["tagged"], 3)  # Flowers, Henry, Fannin

        tags = {
            row["player_id"]: row["tag"]
            for row in self.conn.execute("SELECT player_id, tag FROM player_manual_tags").fetchall()
        }
        self.assertEqual(tags[1], "sleeper")
        self.assertEqual(tags[2], "shy_away")
        self.assertEqual(tags[3], "sleeper")

    def test_ambiguous_verdicts_are_skipped_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = import_manual_calls(self._write_notes(tmp), conn=self.conn)

        self.assertEqual(len(result["skipped"]), 2)
        skipped_text = "\n".join(result["skipped"])
        self.assertIn("Trey McBride", skipped_text)
        self.assertIn("Travis Hunter", skipped_text)

        # Neither ambiguous player should end up tagged.
        tagged_ids = {
            row["player_id"] for row in self.conn.execute("SELECT player_id FROM player_manual_tags").fetchall()
        }
        self.assertEqual(tagged_ids, {1, 2, 3})

    def test_unresolved_names_are_queued_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = import_manual_calls(self._write_notes(tmp), conn=self.conn)

        self.assertEqual(result["unresolved"], 1)
        unresolved = list_unresolved(self.conn, source=MANUAL_NOTES_SOURCE)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["raw_name"], "Some Rookie Nobody Has Heard Of")

    def test_source_used_for_matching_is_generic(self):
        # Confidentiality rule: no provider-specific string in the source tag.
        self.assertNotIn("etr", MANUAL_NOTES_SOURCE.lower())
        self.assertNotIn("podcast", MANUAL_NOTES_SOURCE.lower())

    def test_rerun_is_idempotent_on_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_notes(tmp)
            import_manual_calls(path, conn=self.conn)
            import_manual_calls(path, conn=self.conn)

        total = self.conn.execute("SELECT COUNT(*) AS c FROM player_manual_tags").fetchone()["c"]
        self.assertEqual(total, 3)  # upsert, not duplicate rows


if __name__ == "__main__":
    unittest.main()
