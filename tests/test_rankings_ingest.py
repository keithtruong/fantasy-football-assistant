import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.ingest import rankings as rankings_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


FAKE_ROWS = [
    {"full_name": "Ja'Marr Chase", "position": "WR", "nfl_team": "CIN", "rank": 1, "adp": 1.2, "position_rank": "WR1"},
    {"full_name": "Christian McCaffrey", "position": "RB", "nfl_team": "SF", "rank": 2, "adp": 2.5, "position_rank": "RB1"},
    {"full_name": "Totally Unknown Rookie", "position": "WR", "nfl_team": "NYJ", "rank": 3, "adp": 3.1, "position_rank": "WR2"},
]


class TestSyncDraftRankings(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, \"Ja'Marr Chase\", 'WR')"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (2, 'Christian McCaffrey', 'RB')"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.rankings.rankings_api.get_draft_rankings", return_value=FAKE_ROWS)
    def test_matches_known_players_and_queues_unknown(self, _mock):
        rankings_ingest.sync_draft_rankings(self.conn, season=2026, scoring_format="full_ppr")

        rows = self.conn.execute(
            "SELECT p.full_name, r.rank, r.adp, r.scoring_format FROM rankings r "
            "JOIN players p ON p.player_id = r.player_id ORDER BY r.rank"
        ).fetchall()
        self.assertEqual(len(rows), 2)  # unknown rookie NOT auto-created
        self.assertEqual(rows[0]["full_name"], "Ja'Marr Chase")
        self.assertEqual(rows[0]["scoring_format"], "full_ppr")

        unresolved = self.conn.execute(
            "SELECT raw_name FROM unresolved_aliases WHERE source = 'rankings_provider'"
        ).fetchall()
        self.assertEqual([r["raw_name"] for r in unresolved], ["Totally Unknown Rookie"])

        # No new canonical player was created for the unmatched name.
        player_count = self.conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
        self.assertEqual(player_count, 2)

    @patch("ffassistant.ingest.rankings.rankings_api.get_draft_rankings", return_value=FAKE_ROWS)
    def test_resync_replaces_rather_than_duplicates(self, _mock):
        rankings_ingest.sync_draft_rankings(self.conn, season=2026, scoring_format="full_ppr")
        rankings_ingest.sync_draft_rankings(self.conn, season=2026, scoring_format="full_ppr")

        count = self.conn.execute("SELECT COUNT(*) AS c FROM rankings").fetchone()["c"]
        self.assertEqual(count, 2)  # not 4

    @patch("ffassistant.ingest.rankings.rankings_api.get_draft_rankings", return_value=FAKE_ROWS)
    def test_different_scoring_formats_coexist(self, _mock):
        rankings_ingest.sync_draft_rankings(self.conn, season=2026, scoring_format="full_ppr")
        rankings_ingest.sync_draft_rankings(self.conn, season=2026, scoring_format="superflex")

        count = self.conn.execute("SELECT COUNT(*) AS c FROM rankings").fetchone()["c"]
        self.assertEqual(count, 4)  # 2 formats x 2 matched players, independent of each other

        formats = {
            r["scoring_format"] for r in self.conn.execute("SELECT DISTINCT scoring_format FROM rankings")
        }
        self.assertEqual(formats, {"full_ppr", "superflex"})


FAKE_WEEKLY_ROWS_BY_POSITION = {
    "QB": [
        {
            "full_name": "Josh Allen",
            "position": "QB",
            "nfl_team": "BUF",
            "rank": 1,
            "position_rank": "QB1",
            "bye_week": 7,
            "opponent": "MIA",
        }
    ],
    "RB": [
        {
            "full_name": "Totally Unknown Rookie RB",
            "position": "RB",
            "nfl_team": "NYJ",
            "rank": 1,
            "position_rank": "RB1",
            "bye_week": 9,
            "opponent": "DAL",
        }
    ],
    "WR": [],
    "TE": [],
    "DST": [],
    "K": [],
}


def fake_get_weekly_rankings(season, week, position):
    return FAKE_WEEKLY_ROWS_BY_POSITION.get(position, [])


class TestSyncWeeklyRankings(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Josh Allen', 'QB')"
        )
        self.conn.commit()

    @patch(
        "ffassistant.ingest.rankings.rankings_api.get_weekly_rankings",
        side_effect=fake_get_weekly_rankings,
    )
    def test_matches_known_players_and_queues_unknown_across_positions(self, _mock):
        rankings_ingest.sync_weekly_rankings(self.conn, season=2026, week=1)

        rows = self.conn.execute(
            "SELECT p.full_name, r.rank, r.week, r.scoring_format FROM rankings r "
            "JOIN players p ON p.player_id = r.player_id WHERE r.ranking_type = 'weekly'"
        ).fetchall()
        self.assertEqual(len(rows), 1)  # only Josh Allen matched
        self.assertEqual(rows[0]["full_name"], "Josh Allen")
        self.assertEqual(rows[0]["week"], 1)
        self.assertEqual(rows[0]["scoring_format"], "half_ppr")

        unresolved = self.conn.execute(
            "SELECT raw_name FROM unresolved_aliases WHERE source = 'rankings_provider'"
        ).fetchall()
        self.assertEqual([r["raw_name"] for r in unresolved], ["Totally Unknown Rookie RB"])

        player_count = self.conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
        self.assertEqual(player_count, 1)  # unmatched name NOT auto-created

    @patch(
        "ffassistant.ingest.rankings.rankings_api.get_weekly_rankings",
        side_effect=fake_get_weekly_rankings,
    )
    def test_resync_replaces_rather_than_duplicates(self, _mock):
        rankings_ingest.sync_weekly_rankings(self.conn, season=2026, week=1)
        rankings_ingest.sync_weekly_rankings(self.conn, season=2026, week=1)

        count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'weekly'"
        ).fetchone()["c"]
        self.assertEqual(count, 1)  # not 2

    @patch(
        "ffassistant.ingest.rankings.rankings_api.get_weekly_rankings",
        side_effect=fake_get_weekly_rankings,
    )
    def test_different_weeks_coexist(self, _mock):
        rankings_ingest.sync_weekly_rankings(self.conn, season=2026, week=1)
        rankings_ingest.sync_weekly_rankings(self.conn, season=2026, week=2)

        count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM rankings WHERE ranking_type = 'weekly'"
        ).fetchone()["c"]
        self.assertEqual(count, 2)  # week 1 and week 2 both kept


FAKE_TIERS_BY_POSITION = {
    "QB": [{"full_name": "Josh Allen", "tier": 1}],
    "RB": [{"full_name": "Totally Unknown Deep Sleeper", "tier": 12}],
    "WR": [],
    "TE": [],
}


def fake_get_tiers(position):
    return FAKE_TIERS_BY_POSITION.get(position, [])


class TestSyncTiers(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (1, 'Josh Allen', 'QB')"
        )
        self.conn.commit()
        # Pre-existing draft rankings across two scoring formats, as if sync_draft_rankings
        # already ran — tier should update both, not just one.
        self.conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) "
            "VALUES (1, 'draft', 2026, 'full_ppr', 5)"
        )
        self.conn.execute(
            "INSERT INTO rankings (player_id, ranking_type, season, scoring_format, rank) "
            "VALUES (1, 'draft', 2026, 'superflex', 3)"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.rankings.rankings_api.get_tiers", side_effect=fake_get_tiers)
    def test_updates_tier_across_all_scoring_formats(self, _mock):
        rankings_ingest.sync_tiers(self.conn, season=2026)

        tiers = {
            r["scoring_format"]: r["tier"]
            for r in self.conn.execute(
                "SELECT scoring_format, tier FROM rankings WHERE player_id = 1"
            )
        }
        self.assertEqual(tiers, {"full_ppr": 1, "superflex": 1})

    @patch("ffassistant.ingest.rankings.rankings_api.get_tiers", side_effect=fake_get_tiers)
    def test_unmatched_tier_name_is_queued_not_created(self, _mock):
        rankings_ingest.sync_tiers(self.conn, season=2026)

        unresolved = self.conn.execute(
            "SELECT raw_name FROM unresolved_aliases WHERE source = 'rankings_provider'"
        ).fetchall()
        self.assertEqual([r["raw_name"] for r in unresolved], ["Totally Unknown Deep Sleeper"])

        player_count = self.conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
        self.assertEqual(player_count, 1)  # no new player auto-created


if __name__ == "__main__":
    unittest.main()
