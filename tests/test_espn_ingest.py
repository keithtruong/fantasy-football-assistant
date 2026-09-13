import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from ffassistant.ingest import espn as espn_ingest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


FAKE_SETTINGS = {
    "team_count": 2,
    "scoring": {"PTD": 4, "PY": 0.04},
    "roster_slots": {"QB": 1, "RB": 2, "BENCH": 5},
}

FAKE_TEAMS = [
    {
        "platform_team_id": "1",
        "team_name": "Keith's Team",
        "waiver_priority": 2,
        "wins": 3,
        "losses": 1,
        "ties": 0,
        "points_for": 450.5,
        "points_against": 400.0,
        "playoff_pct": 88.0,
        "standing": 1,
        "players": [
            {
                "source_player_id": "101",
                "full_name": "Justin Jefferson",
                "position": "WR",
                "nfl_team": "MIN",
                "injury_status": "ACTIVE",
            },
            {
                "source_player_id": "102",
                "full_name": "Banged Up Guy",
                "position": "RB",
                "nfl_team": "SEA",
                "injury_status": "QUESTIONABLE",
            },
        ],
    },
    {
        "platform_team_id": "2",
        "team_name": "Rival Team",
        "waiver_priority": 1,
        "wins": 1,
        "losses": 3,
        "ties": 0,
        "points_for": 380.0,
        "points_against": 430.0,
        "playoff_pct": 15.0,
        "standing": 2,
        "players": [
            {
                "source_player_id": "201",
                "full_name": "Some Other Guy",
                "position": "RB",
                "nfl_team": "NYJ",
                "injury_status": "OUT",
            },
        ],
    },
]


class TestSyncLeague(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute(
            "INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 2)"
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (10, 'Justin Jefferson', 'WR')"
        )
        self.conn.commit()

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_full_sync_without_week_skips_player_status(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        scoring = {r["stat_key"]: r["points"] for r in self.conn.execute("SELECT * FROM league_scoring")}
        self.assertEqual(scoring, {"PTD": 4, "PY": 0.04})

        teams = self.conn.execute("SELECT * FROM teams ORDER BY platform_team_id").fetchall()
        self.assertEqual(len(teams), 2)

        # Pre-seeded canonical player matched, not duplicated.
        jefferson_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name = 'Justin Jefferson'"
        ).fetchone()["c"]
        self.assertEqual(jefferson_count, 1)

        # New players auto-created.
        new_player_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE full_name IN ('Banged Up Guy', 'Some Other Guy')"
        ).fetchone()["c"]
        self.assertEqual(new_player_count, 2)

        # No week passed -> no player_status rows written.
        status_count = self.conn.execute("SELECT COUNT(*) AS c FROM player_status").fetchone()["c"]
        self.assertEqual(status_count, 0)

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_waiver_priority_synced_and_updated_on_resync(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        priorities = {
            r["platform_team_id"]: r["waiver_priority"] for r in self.conn.execute("SELECT * FROM teams")
        }
        self.assertEqual(priorities, {"1": 2, "2": 1})

        # A resync with a changed priority (waiver order rotates week to week)
        # updates in place rather than leaving the stale value.
        updated_teams = [dict(t) for t in FAKE_TEAMS]
        updated_teams[0]["waiver_priority"] = 1
        updated_teams[1]["waiver_priority"] = 2
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=updated_teams):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        priorities = {
            r["platform_team_id"]: r["waiver_priority"] for r in self.conn.execute("SELECT * FROM teams")
        }
        self.assertEqual(priorities, {"1": 1, "2": 2})

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_record_synced(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        records = {
            r["platform_team_id"]: (r["wins"], r["losses"], r["ties"])
            for r in self.conn.execute("SELECT * FROM teams")
        }
        self.assertEqual(records, {"1": (3, 1, 0), "2": (1, 3, 0)})

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_standings_metadata_synced(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        rows = {
            r["platform_team_id"]: (r["points_for"], r["points_against"], r["playoff_pct"], r["standing"])
            for r in self.conn.execute("SELECT * FROM teams")
        }
        self.assertEqual(rows, {"1": (450.5, 400.0, 88.0, 1), "2": (380.0, 430.0, 15.0, 2)})

        # A resync with updated standings (a team's playoff odds move week to
        # week) updates in place rather than leaving the stale value.
        updated_teams = [dict(t) for t in FAKE_TEAMS]
        updated_teams[0]["playoff_pct"] = 95.0
        updated_teams[0]["standing"] = 1
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=updated_teams):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        playoff_pct = self.conn.execute(
            "SELECT playoff_pct FROM teams WHERE platform_team_id = '1'"
        ).fetchone()["playoff_pct"]
        self.assertEqual(playoff_pct, 95.0)

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=[{k: v for k, v in FAKE_TEAMS[0].items() if k not in ("points_for", "points_against", "playoff_pct", "standing")}])
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_standings_metadata_missing_from_source_defaults_to_null_not_crash(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)
        row = self.conn.execute("SELECT * FROM teams WHERE platform_team_id = '1'").fetchone()
        self.assertIsNone(row["playoff_pct"])
        self.assertIsNone(row["standing"])

    @patch(
        "ffassistant.ingest.espn.espn_api.get_matchups",
        return_value=[
            {"platform_team_id": "1", "opponent_platform_team_id": "2"},
            {"platform_team_id": "2", "opponent_platform_team_id": "1"},
        ],
    )
    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_matchup_synced_when_week_given(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)

        rows = self.conn.execute(
            """
            SELECT t.platform_team_id AS mine, o.platform_team_id AS opponent
            FROM weekly_matchups wm
            JOIN teams t ON t.team_id = wm.team_id
            JOIN teams o ON o.team_id = wm.opponent_team_id
            WHERE wm.league_id = 1 AND wm.season = 2026 AND wm.week = 5
            """
        ).fetchall()
        pairs = {(r["mine"], r["opponent"]) for r in rows}
        self.assertEqual(pairs, {("1", "2"), ("2", "1")})

    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_no_matchup_synced_without_week(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        count = self.conn.execute("SELECT COUNT(*) AS c FROM weekly_matchups").fetchone()["c"]
        self.assertEqual(count, 0)

    @patch("ffassistant.ingest.espn.espn_api.get_matchups", return_value=[])
    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_sync_with_week_records_injury_status(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)

        statuses = {
            r["status"]
            for r in self.conn.execute(
                """
                SELECT ps.status FROM player_status ps
                JOIN players p ON p.player_id = ps.player_id
                WHERE p.full_name = 'Banged Up Guy'
                """
            )
        }
        self.assertEqual(statuses, {"questionable"})

        out_status = self.conn.execute(
            """
            SELECT ps.status FROM player_status ps
            JOIN players p ON p.player_id = ps.player_id
            WHERE p.full_name = 'Some Other Guy'
            """
        ).fetchone()["status"]
        self.assertEqual(out_status, "out")

    @patch("ffassistant.ingest.espn.espn_api.get_matchups", return_value=[])
    @patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS)
    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_replaces_roster_without_duplicating_teams(self, *_mocks):
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)
        espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026, week=5)

        team_count = self.conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
        self.assertEqual(team_count, 2)

        keiths_team = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '1'"
        ).fetchone()["team_id"]
        spot_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM roster_spots WHERE team_id = ?", (keiths_team,)
        ).fetchone()["c"]
        self.assertEqual(spot_count, 2)  # not 4

    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_resync_with_fewer_teams_removes_the_dropped_one(self, mock_settings):
        # Real incident: an owner left / ESPN reassigned team IDs across seasons,
        # and old teams kept accumulating instead of being cleaned up.
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2025)

        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS[:1]):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        teams = self.conn.execute("SELECT platform_team_id FROM teams").fetchall()
        self.assertEqual([t["platform_team_id"] for t in teams], ["1"])  # "2" (Rival Team) is gone

    @patch("ffassistant.ingest.espn.espn_api.get_box_scores")
    def test_box_scores_written_and_team_score_derivable(self, mock_box_scores):
        # Teams must already exist (from a prior roster sync) — sync_box_scores
        # doesn't create them.
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_box_scores.return_value = [
            {
                "platform_team_id": "1",
                "players": [
                    {
                        "source_player_id": "101",
                        "full_name": "Justin Jefferson",
                        "position": "WR",
                        "nfl_team": "MIN",
                        "slot_name": "WR",
                        "points": 18.4,
                    },
                    {
                        "source_player_id": "102",
                        "full_name": "Banged Up Guy",
                        "position": "RB",
                        "nfl_team": "SEA",
                        "slot_name": "BENCH",
                        "points": 2.0,
                    },
                ],
            }
        ]

        written = espn_ingest.sync_box_scores(self.conn, league_id=1, espn_league_id=999, season=2026, week=1)
        self.assertEqual(written, 2)

        team_id = self.conn.execute("SELECT team_id FROM teams WHERE platform_team_id = '1'").fetchone()["team_id"]
        team_score = self.conn.execute(
            "SELECT SUM(points) AS total FROM weekly_box_scores "
            "WHERE league_id = 1 AND season = 2026 AND week = 1 AND team_id = ? AND slot_name NOT IN ('BENCH', 'IR')",
            (team_id,),
        ).fetchone()["total"]
        self.assertEqual(team_score, 18.4)  # bench points excluded from the team's started score

    @patch("ffassistant.ingest.espn.espn_api.get_box_scores")
    def test_box_scores_capture_game_date_and_projected_points(self, mock_box_scores):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_box_scores.return_value = [
            {
                "platform_team_id": "1",
                "players": [
                    {
                        "source_player_id": "101",
                        "full_name": "Justin Jefferson",
                        "position": "WR",
                        "nfl_team": "MIN",
                        "slot_name": "WR",
                        "points": 18.4,
                        "game_date": "2026-09-07T13:00:00",
                        "projected_points": 15.0,
                    },
                    {
                        "source_player_id": "102",
                        "full_name": "No Timing Data Guy",
                        "position": "RB",
                        "nfl_team": "SEA",
                        "slot_name": "BENCH",
                        "points": 2.0,
                        # no game_date/projected_points keys at all — must not KeyError
                    },
                ],
            }
        ]

        espn_ingest.sync_box_scores(self.conn, league_id=1, espn_league_id=999, season=2026, week=1)

        rows = {
            r["player_id"]: r
            for r in self.conn.execute(
                "SELECT wbs.*, p.full_name FROM weekly_box_scores wbs JOIN players p ON p.player_id = wbs.player_id "
                "WHERE wbs.league_id = 1 AND wbs.season = 2026 AND wbs.week = 1"
            )
        }
        jefferson = next(r for r in rows.values() if r["full_name"] == "Justin Jefferson")
        self.assertEqual(jefferson["game_date"], "2026-09-07T13:00:00")
        self.assertEqual(jefferson["projected_points"], 15.0)

        no_timing = next(r for r in rows.values() if r["full_name"] == "No Timing Data Guy")
        self.assertIsNone(no_timing["game_date"])
        self.assertIsNone(no_timing["projected_points"])

    @patch("ffassistant.ingest.espn.espn_api.get_box_scores")
    def test_box_scores_resync_replaces_rather_than_duplicates(self, mock_box_scores):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        player_row = {
            "source_player_id": "101",
            "full_name": "Justin Jefferson",
            "position": "WR",
            "nfl_team": "MIN",
            "slot_name": "WR",
            "points": 18.4,
        }
        mock_box_scores.return_value = [{"platform_team_id": "1", "players": [player_row]}]
        espn_ingest.sync_box_scores(self.conn, league_id=1, espn_league_id=999, season=2026, week=1)

        updated_row = dict(player_row, points=20.1)
        mock_box_scores.return_value = [{"platform_team_id": "1", "players": [updated_row]}]
        espn_ingest.sync_box_scores(self.conn, league_id=1, espn_league_id=999, season=2026, week=1)

        rows = self.conn.execute(
            "SELECT points FROM weekly_box_scores WHERE league_id = 1 AND season = 2026 AND week = 1"
        ).fetchall()
        self.assertEqual(len(rows), 1)  # not 2 — the resync replaced, didn't duplicate
        self.assertEqual(rows[0]["points"], 20.1)

    @patch("ffassistant.ingest.espn.espn_api.get_box_scores")
    def test_box_scores_skip_team_not_in_teams_table(self, mock_box_scores):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_box_scores.return_value = [
            {
                "platform_team_id": "999",  # not one of FAKE_TEAMS' platform_team_ids
                "players": [
                    {
                        "source_player_id": "301",
                        "full_name": "Ghost Team Guy",
                        "position": "RB",
                        "nfl_team": "DAL",
                        "slot_name": "RB",
                        "points": 5.0,
                    }
                ],
            }
        ]

        written = espn_ingest.sync_box_scores(self.conn, league_id=1, espn_league_id=999, season=2026, week=1)
        self.assertEqual(written, 0)

    @patch("ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS)
    def test_stale_team_with_draft_picks_is_not_removed(self, mock_settings):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2025)

        rival_team_id = self.conn.execute(
            "SELECT team_id FROM teams WHERE platform_team_id = '2'"
        ).fetchone()["team_id"]
        self.conn.execute(
            "INSERT INTO draft_picks (league_id, season, round, pick_number, team_id, player_id) "
            "VALUES (1, 2025, 1, 1, ?, NULL)",
            (rival_team_id,),
        )
        self.conn.commit()

        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS[:1]):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        teams = {t["platform_team_id"] for t in self.conn.execute("SELECT platform_team_id FROM teams")}
        self.assertEqual(teams, {"1", "2"})  # "2" kept — real draft pick depends on it

    @patch("ffassistant.ingest.espn.espn_api.get_matchups")
    def test_sync_weekly_matchups_written_both_sides(self, mock_matchups):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_matchups.return_value = [
            {"platform_team_id": "1", "opponent_platform_team_id": "2"},
            {"platform_team_id": "2", "opponent_platform_team_id": "1"},
        ]

        written = espn_ingest.sync_weekly_matchups(self.conn, league_id=1, espn_league_id=999, season=2025, week=1)
        self.assertEqual(written, 2)

        rows = self.conn.execute(
            "SELECT team_id, opponent_team_id FROM weekly_matchups WHERE league_id = 1 AND season = 2025 AND week = 1"
        ).fetchall()
        self.assertEqual(len(rows), 2)

    @patch("ffassistant.ingest.espn.espn_api.get_matchups")
    def test_sync_weekly_matchups_does_not_touch_teams_or_rosters(self, mock_matchups):
        # The whole point of this function: syncing a *historical* season's
        # matchups must never clobber the live teams/roster_spots rows for
        # the current season, unlike calling sync_league(year=<old year>) would.
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        teams_before = [dict(r) for r in self.conn.execute("SELECT * FROM teams ORDER BY team_id")]
        roster_before = [dict(r) for r in self.conn.execute("SELECT * FROM roster_spots ORDER BY team_id, player_id")]

        mock_matchups.return_value = [
            {"platform_team_id": "1", "opponent_platform_team_id": "2"},
            {"platform_team_id": "2", "opponent_platform_team_id": "1"},
        ]
        espn_ingest.sync_weekly_matchups(self.conn, league_id=1, espn_league_id=999, season=2025, week=1)

        teams_after = [dict(r) for r in self.conn.execute("SELECT * FROM teams ORDER BY team_id")]
        roster_after = [dict(r) for r in self.conn.execute("SELECT * FROM roster_spots ORDER BY team_id, player_id")]
        self.assertEqual(teams_before, teams_after)
        self.assertEqual(roster_before, roster_after)

    @patch("ffassistant.ingest.espn.espn_api.get_matchups")
    def test_sync_weekly_matchups_resync_replaces_rather_than_duplicates(self, mock_matchups):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_matchups.return_value = [
            {"platform_team_id": "1", "opponent_platform_team_id": "2"},
            {"platform_team_id": "2", "opponent_platform_team_id": "1"},
        ]
        espn_ingest.sync_weekly_matchups(self.conn, league_id=1, espn_league_id=999, season=2025, week=1)
        espn_ingest.sync_weekly_matchups(self.conn, league_id=1, espn_league_id=999, season=2025, week=1)

        rows = self.conn.execute(
            "SELECT * FROM weekly_matchups WHERE league_id = 1 AND season = 2025 AND week = 1"
        ).fetchall()
        self.assertEqual(len(rows), 2)  # not 4 — the resync replaced, didn't duplicate

    @patch("ffassistant.ingest.espn.espn_api.get_matchups")
    def test_sync_weekly_matchups_skips_team_not_in_teams_table(self, mock_matchups):
        with patch("ffassistant.ingest.espn.espn_api.get_teams", return_value=FAKE_TEAMS), patch(
            "ffassistant.ingest.espn.espn_api.get_league_settings", return_value=FAKE_SETTINGS
        ):
            espn_ingest.sync_league(self.conn, league_id=1, espn_league_id=999, year=2026)

        mock_matchups.return_value = [
            {"platform_team_id": "1", "opponent_platform_team_id": "999"},  # 999 not in teams table
            {"platform_team_id": "999", "opponent_platform_team_id": "1"},
        ]
        written = espn_ingest.sync_weekly_matchups(self.conn, league_id=1, espn_league_id=999, season=2025, week=1)
        self.assertEqual(written, 0)


if __name__ == "__main__":
    unittest.main()
