import sqlite3
import unittest
from pathlib import Path

from ffassistant.recap_data import gather_recap_data

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ffassistant" / "schema.sql"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


class TestGatherRecapData(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 2)")
        self.conn.execute("INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (10, 1, '1', 'Team Ten')")
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name, display_name) "
            "VALUES (20, 1, '2', 'Team Twenty', 'Keith Override')"
        )
        self.conn.executemany(
            "INSERT INTO roster_slots (league_id, slot_name, slot_count) VALUES (1, ?, ?)",
            [("QB", 1), ("RB", 1), ("BENCH", 3)],
        )
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position, is_rookie) VALUES (?, ?, ?, ?)",
            [
                (100, "Team Ten QB", "QB", 0),
                (101, "Team Ten RB", "RB", 1),
                (102, "Team Ten Bench RB", "RB", 0),
                (200, "Team Twenty QB", "QB", 0),
                (201, "Team Twenty RB", "RB", 0),
            ],
        )
        self.conn.executemany(
            "INSERT INTO weekly_box_scores (league_id, season, week, team_id, player_id, slot_name, points) "
            "VALUES (1, 2025, 1, ?, ?, ?, ?)",
            [
                (10, 100, "QB", 20.0),
                (10, 101, "RB", 5.0),
                (10, 102, "BENCH", 25.0),  # should've started over 101
                (20, 200, "QB", 10.0),
                (20, 201, "RB", 15.0),
            ],
        )
        self.conn.executemany(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (1, 2025, 1, ?, ?)",
            [(10, 20), (20, 10)],
        )
        self.conn.execute(
            "INSERT INTO players (player_id, full_name, position) VALUES (300, 'Waiver Steal', 'RB')"
        )
        self.conn.execute(
            "INSERT INTO weekly_free_agent_scores (league_id, season, week, player_id, points, projected_points) "
            "VALUES (1, 2025, 1, 300, 12.0, 3.0)"
        )
        self.conn.commit()

    def test_team_names_use_display_name_override(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["team_names"], {10: "Team Ten", 20: "Keith Override"})

    def test_team_real_names_ignore_display_name_override(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["team_real_names"], {10: "Team Ten", 20: "Team Twenty"})

    def test_team_scores_exclude_bench(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["team_scores"], {10: 25.0, 20: 25.0})  # bench's 25.0 excluded for team 10

    def test_high_low(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        # both teams tie at 25.0 started points — either could be "highest"/"lowest", just check points
        self.assertEqual(result["high_low"]["highest"]["points"], 25.0)
        self.assertEqual(result["high_low"]["lowest"]["points"], 25.0)

    def test_matchups_paired_from_weekly_matchups(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(len(result["matchups"]), 1)
        self.assertEqual(result["matchups"][0]["margin"], 0.0)

    def test_optimal_lineup_by_team_flags_the_bench_mistake(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        team_10 = result["optimal_lineup_by_team"][10]
        self.assertEqual(team_10["actual_points"], 25.0)  # 20 (QB) + 5 (RB)
        self.assertEqual(team_10["optimal_points"], 45.0)  # 20 (QB) + 25 (bench RB should've started)

    def test_gaffes_by_team_flags_the_same_mistake(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        gaffes = result["gaffes_by_team"][10]
        self.assertEqual(len(gaffes), 1)
        self.assertEqual(gaffes[0]["missed_points"], 20.0)

    def test_best_by_slot_present(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["best_by_slot"]["QB"]["team_id"], 10)  # 20.0 beats 10.0
        self.assertIsNone(result["best_by_slot"]["K"])  # no K data at all

    def test_waiver_wire_flags_the_outlier_that_cleared_the_floor(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(len(result["waiver_wire"]), 1)
        steal = result["waiver_wire"][0]
        self.assertEqual(steal["full_name"], "Waiver Steal")
        self.assertEqual(steal["points"], 12.0)
        self.assertEqual(steal["projected_points"], 3.0)
        self.assertEqual(steal["points_over_projection"], 9.0)
        self.assertTrue(result["waiver_wire_synced"])

    def test_matchup_details_present_and_enriched(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(len(result["matchup_details"]), 1)
        detail = result["matchup_details"][0]
        self.assertTrue(detail["is_matchup_of_the_week"])  # only matchup that week
        self.assertIn("top_players", detail["team_a_detail"])
        self.assertIn("score_by_checkpoint", detail["team_b_detail"])

    def test_top_players_carry_is_rookie_from_the_players_table(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        team_10_players = result["matchup_details"][0]["team_a_detail"]["top_players"]
        by_name = {p["full_name"]: p["is_rookie"] for p in team_10_players}
        self.assertEqual(by_name["Team Ten QB"], False)
        self.assertEqual(by_name["Team Ten RB"], True)

    def test_empty_week_returns_empty_shape_not_error(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=17)
        self.assertEqual(result["team_scores"], {})
        self.assertEqual(result["high_low"], {"highest": None, "lowest": None})
        self.assertEqual(result["matchups"], [])
        self.assertEqual(result["matchup_details"], [])
        self.assertEqual(result["optimal_lineup_by_team"], {})
        self.assertEqual(result["waiver_wire"], [])
        self.assertFalse(result["waiver_wire_synced"])

    def test_owner_meta_empty_when_no_owners_rows(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["owner_meta"], {})

    def test_standings_present_for_every_team_regardless_of_sync_status(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual({t["team_id"] for t in result["standings"]}, {10, 20})

    def test_next_week_defaults_to_empty_when_not_synced(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["next_week"], {"week": 2, "matchups": []})


class TestGatherRecapDataWithOwners(unittest.TestCase):
    """A team's owners row (when present) is the name that actually gets
    published — this is the fix for a real incident: ESPN's own team
    display_name for one TAMS owner was a nickname he explicitly didn't want
    published, and the owners table exists specifically to override that."""

    def setUp(self):
        self.conn = make_conn()
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 2)")
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name, display_name) "
            "VALUES (10, 1, '1', 'Some Team Name', 'NotSafeToPublish')"
        )
        self.conn.execute(
            "INSERT INTO owners (team_id, real_name, display_nickname, location) VALUES (10, 'Real Name', 'Safe Nickname', 'Houston')"
        )
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position) VALUES (?, ?, ?)",
            [(100, "Some QB", "QB")],
        )
        self.conn.execute(
            "INSERT INTO weekly_box_scores (league_id, season, week, team_id, player_id, slot_name, points) "
            "VALUES (1, 2025, 1, 10, 100, 'QB', 20.0)"
        )
        self.conn.commit()

    def test_owners_display_nickname_wins_over_teams_display_name(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["team_names"], {10: "Safe Nickname"})
        self.assertNotIn("NotSafeToPublish", result["team_names"].values())

    def test_team_real_name_is_unaffected_by_owners_override(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(result["team_real_names"], {10: "Some Team Name"})

    def test_owner_meta_carries_full_record(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual(
            result["owner_meta"][10],
            {
                "real_name": "Real Name",
                "display_nickname": "Safe Nickname",
                "location": "Houston",
                "notes": None,
                "sibling_team_id": None,
            },
        )

    def test_owner_meta_present_even_for_teams_without_box_scores_yet(self):
        self.conn.execute("INSERT INTO teams (team_id, league_id, platform_team_id, team_name) VALUES (11, 1, '2', 'No Box Scores Team')")
        self.conn.execute("INSERT INTO owners (team_id, display_nickname) VALUES (11, 'Waiting Owner')")
        self.conn.commit()
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertIn(11, result["owner_meta"])
        self.assertNotIn(11, result["team_names"])  # no box scores synced for this team yet


class TestGatherRecapDataNextWeekPreview(unittest.TestCase):
    """Standings + Next Week Preview draw from teams'/weekly_matchups'/
    weekly_box_scores' own week+1 rows — separate sync targets from the
    current week's recap data covered by TestGatherRecapData above."""

    def setUp(self):
        self.conn = make_conn()
        self.conn.execute("INSERT INTO leagues (league_id, name, platform, team_count) VALUES (1, 'Test League', 'espn', 2)")
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name, wins, losses, ties, "
            "points_for, points_against, playoff_pct, standing) "
            "VALUES (10, 1, '1', 'Team Ten', 8, 2, 0, 950.5, 800.0, 92.0, 1)"
        )
        self.conn.execute(
            "INSERT INTO teams (team_id, league_id, platform_team_id, team_name, wins, losses, ties, "
            "points_for, points_against, playoff_pct, standing) "
            "VALUES (20, 1, '2', 'Team Twenty', 6, 4, 0, 900.0, 850.0, 55.0, 2)"
        )
        self.conn.execute(
            "INSERT INTO owners (team_id, display_nickname, sibling_team_id) VALUES (10, 'Ten', NULL)"
        )
        self.conn.execute(
            "INSERT INTO owners (team_id, display_nickname, sibling_team_id) VALUES (20, 'Twenty', NULL)"
        )
        self.conn.executemany(
            "INSERT INTO players (player_id, full_name, position) VALUES (?, ?, ?)",
            [(100, "Team Ten QB", "QB"), (200, "Team Twenty QB", "QB")],
        )
        self.conn.execute(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (1, 2025, 2, 10, 20)"
        )
        self.conn.execute(
            "INSERT INTO weekly_matchups (league_id, season, week, team_id, opponent_team_id) VALUES (1, 2025, 2, 20, 10)"
        )
        self.conn.executemany(
            "INSERT INTO weekly_box_scores (league_id, season, week, team_id, player_id, slot_name, points, projected_points) "
            "VALUES (1, 2025, 2, ?, ?, 'QB', 0.0, ?)",
            [(10, 100, 22.0), (20, 200, 18.0)],
        )
        self.conn.commit()

    def test_standings_ranked_by_espn_standing(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        self.assertEqual([t["team_id"] for t in result["standings"]], [10, 20])
        self.assertEqual(result["standings"][0]["rank"], 1)
        self.assertEqual(result["standings"][0]["team_name"], "Ten")  # owner nickname preferred, same as team_names

    def test_next_week_matchup_built_from_week_plus_one_data(self):
        result = gather_recap_data(self.conn, league_id=1, season=2025, week=1)
        next_week = result["next_week"]
        self.assertEqual(next_week["week"], 2)
        self.assertEqual(len(next_week["matchups"]), 1)
        m = next_week["matchups"][0]
        self.assertEqual({m["team_a"]["team_id"], m["team_b"]["team_id"]}, {10, 20})
        self.assertIn("top_seed_clash", m["tags"])  # standing 1 vs 2
        a_side = m["team_a"] if m["team_a"]["team_id"] == 10 else m["team_b"]
        self.assertEqual(a_side["projected_score"], 22.0)


if __name__ == "__main__":
    unittest.main()
