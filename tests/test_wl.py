import sqlite3
import unittest
from pathlib import Path

from ffassistant.wl import (
    autofill_from_platform_sync,
    derive_outcome,
    sync_league_season_record,
    upsert_guillotine_week,
    upsert_matchup,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestDeriveOutcome(unittest.TestCase):
    def test_win(self):
        self.assertEqual(derive_outcome(120.0, 100.0), "W")

    def test_loss(self):
        self.assertEqual(derive_outcome(90.0, 100.0), "L")

    def test_tie(self):
        self.assertEqual(derive_outcome(100.0, 100.0), "T")


class TestUpsertMatchup(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self.conn.commit()

    def test_inserts_and_derives_outcome(self):
        row = upsert_matchup(self.conn, 1, 2026, 1, 120.0, 100.0)
        self.assertEqual(row["outcome"], "W")
        stored = self.conn.execute("SELECT * FROM matchups WHERE league_history_id = 1").fetchone()
        self.assertEqual(stored["points_for"], 120.0)

    def test_overwrite_updates_not_duplicates(self):
        upsert_matchup(self.conn, 1, 2026, 1, 120.0, 100.0)
        upsert_matchup(self.conn, 1, 2026, 1, 90.0, 100.0)
        rows = self.conn.execute("SELECT * FROM matchups WHERE league_history_id = 1").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "L")


class TestSyncLeagueSeasonRecord(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self.conn.commit()

    def test_creates_row_from_matchups_leaving_payout_fields_null(self):
        upsert_matchup(self.conn, 1, 2026, 1, 120.0, 100.0)  # W
        upsert_matchup(self.conn, 1, 2026, 2, 90.0, 100.0)  # L

        row = sync_league_season_record(self.conn, 1, 2026)

        self.assertEqual(row, {"league_history_id": 1, "season": 2026, "wins": 1, "losses": 1, "ties": 0})
        stored = self.conn.execute(
            "SELECT * FROM league_seasons WHERE league_history_id = 1 AND season = 2026"
        ).fetchone()
        self.assertIsNone(stored["buy_in"])
        self.assertIsNone(stored["finish_position"])

    def test_updates_wins_without_clobbering_buy_in_or_finish(self):
        self.conn.execute(
            "INSERT INTO league_seasons (league_history_id, season, wins, losses, ties, buy_in, finish_position) "
            "VALUES (1, 2026, 0, 0, 0, 50, 3)"
        )
        self.conn.commit()
        upsert_matchup(self.conn, 1, 2026, 1, 120.0, 100.0)  # W

        sync_league_season_record(self.conn, 1, 2026)

        stored = self.conn.execute(
            "SELECT * FROM league_seasons WHERE league_history_id = 1 AND season = 2026"
        ).fetchone()
        self.assertEqual(stored["wins"], 1)
        self.assertEqual(stored["buy_in"], 50)
        self.assertEqual(stored["finish_position"], 3)

    def test_no_matchups_yields_zeroed_record(self):
        row = sync_league_season_record(self.conn, 1, 2026)
        self.assertEqual(row, {"league_history_id": 1, "season": 2026, "wins": 0, "losses": 0, "ties": 0})


class TestUpsertGuillotineWeek(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO league_history (league_history_id, name, format) VALUES (1, 'Guillotine', 'guillotine')"
        )
        self.conn.commit()

    def test_inserts_row(self):
        row = upsert_guillotine_week(self.conn, 1, 2026, 1, 120.0, 80.0, 3, 10)
        self.assertEqual(row["rank"], 3)
        self.assertEqual(row["remaining_count"], 10)
        stored = self.conn.execute("SELECT * FROM guillotine_weeks WHERE league_history_id = 1").fetchone()
        self.assertEqual(stored["points_for"], 120.0)
        self.assertEqual(stored["eliminated_points"], 80.0)

    def test_overwrite_updates_not_duplicates(self):
        upsert_guillotine_week(self.conn, 1, 2026, 1, 120.0, 80.0, 3, 10)
        upsert_guillotine_week(self.conn, 1, 2026, 1, 110.0, 85.0, 2, 9)
        rows = self.conn.execute("SELECT * FROM guillotine_weeks WHERE league_history_id = 1").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rank"], 2)
        self.assertEqual(rows[0]["remaining_count"], 9)


class TestAutofillFromPlatformSync(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def _add_league(self, league_id, name, platform="espn"):
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count, active) VALUES (?, ?, ?, 10, 1)",
            (league_id, name, platform),
        )

    def _add_team(self, team_id, league_id, is_mine=1, wins=None, losses=None, points_for=None, points_against=None):
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, team_name, is_mine, wins, losses, points_for, points_against) "
            "VALUES (?, ?, 'Mine', ?, ?, ?, ?, ?)",
            (team_id, league_id, is_mine, wins, losses, points_for, points_against),
        )

    def test_fills_matchup_from_synced_team_record(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self._add_league(10, "BC1 2026")
        self._add_team(100, 10, wins=1, losses=0, points_for=120.5, points_against=98.2)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [
            {
                "league_history_name": "BC1",
                "status": "filled",
                "league_history_id": 1,
                "season": 2026,
                "week": 1,
                "points_for": 120.5,
                "points_against": 98.2,
                "outcome": "W",
                "playoff_round": None,
            }
        ])
        stored = self.conn.execute("SELECT * FROM matchups WHERE league_history_id = 1").fetchone()
        self.assertEqual(stored["outcome"], "W")

    def test_skips_league_with_no_matching_platform_league_this_season(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'Chrisnfriends')")
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "Chrisnfriends", "status": "no_platform_match"}])

    def test_skips_league_with_no_team_flagged_is_mine(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self._add_league(10, "BC1 2026")
        self._add_team(100, 10, is_mine=0, wins=1, losses=0, points_for=120.5, points_against=98.2)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "BC1", "status": "no_my_team_flagged"}])

    def test_skips_league_with_no_traditional_win_loss_record(self):
        # Guillotine-style: wins/losses come back None from the connector.
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'Guillotine')")
        self._add_league(10, "Guillotine 2026", platform="yahoo")
        self._add_team(100, 10, wins=None, losses=None, points_for=92.18, points_against=None)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "Guillotine", "status": "no_traditional_record"}])

    def test_skips_when_points_for_is_zero_treated_as_not_final(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self._add_league(10, "BC1 2026")
        self._add_team(100, 10, wins=0, losses=0, points_for=0.0, points_against=0.0)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "BC1", "status": "not_final_yet"}])

    def test_skips_when_points_for_present_but_points_against_missing(self):
        # Sleeper shape before fpts_against exists at all.
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC3')")
        self._add_league(10, "BC3 2026", platform="sleeper")
        self._add_team(100, 10, wins=0, losses=0, points_for=120.5, points_against=None)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [{"league_history_name": "BC3", "status": "not_final_yet"}])

    def test_inactive_league_history_is_ignored(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name, active) VALUES (1, 'Chrisnfriends', 0)")
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        self.assertEqual(results, [])

    def test_multiple_leagues_handled_independently(self):
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (1, 'BC1')")
        self.conn.execute("INSERT INTO league_history (league_history_id, name) VALUES (2, 'BC2')")
        self._add_league(10, "BC1 2026")
        self._add_team(100, 10, wins=1, losses=0, points_for=120.5, points_against=98.2)
        self._add_league(11, "BC2 2026")
        self._add_team(101, 11, wins=0, losses=0, points_for=0.0, points_against=0.0)
        self.conn.commit()

        results = autofill_from_platform_sync(self.conn, 2026, 1)

        statuses = {r["league_history_name"]: r["status"] for r in results}
        self.assertEqual(statuses, {"BC1": "filled", "BC2": "not_final_yet"})


if __name__ == "__main__":
    unittest.main()
