import json
import unittest
from unittest.mock import MagicMock, patch

from ffassistant.connectors import rankings


def make_page_html(rows: list[dict]) -> str:
    payload = json.dumps({"rows": rows})
    # Mirrors the real page's structure: a JS variable assigned via JSON.parse
    # inside a template-literal (backtick) string, embedded in a script tag.
    return f"<html><script>window.SOME_DATASET_123 = JSON.parse(`{payload}`)</script></html>"


FAKE_ROWS = [
    {"player": "Ja'Marr Chase", "position": "wr", "team": "cin", "etrRank": 1, "adp": 1.2, "posRankEtr": "WR1"},
    {"player": "Christian McCaffrey", "position": "rb", "team": "sf", "etrRank": 2, "adp": 2.5, "posRankEtr": "RB1"},
    {"player": "No Rank Guy", "position": "wr", "team": "nyj", "etrRank": None, "adp": None, "posRankEtr": None},
]


class TestExtractRows(unittest.TestCase):
    def test_extracts_rows_from_embedded_json(self):
        html = make_page_html(FAKE_ROWS)
        rows = rankings._extract_rows(html)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["player"], "Ja'Marr Chase")

    def test_raises_when_marker_missing(self):
        with self.assertRaises(ValueError):
            rankings._extract_rows("<html>not logged in</html>")

    def test_handles_braces_inside_string_values(self):
        rows_with_braces = [{"player": "Player {with} braces", "etrRank": 1}]
        html = make_page_html(rows_with_braces)
        rows = rankings._extract_rows(html)
        self.assertEqual(rows[0]["player"], "Player {with} braces")


class TestGetDraftRankings(unittest.TestCase):
    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_parses_and_filters_malformed_rows(self, mock_get, mock_config):
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "draft_urls": {"full_ppr": "https://example.invalid/full-ppr"},
        }
        mock_response = MagicMock()
        mock_response.content = make_page_html(FAKE_ROWS).encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_draft_rankings("full_ppr")

        # The unranked row is filtered out.
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["full_name"], "Ja'Marr Chase")
        self.assertEqual(result[0]["position"], "WR")
        self.assertEqual(result[0]["nfl_team"], "CIN")
        self.assertEqual(result[0]["rank"], 1)
        self.assertEqual(result[0]["adp"], 1.2)

        # Cookie was passed through to the request.
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["cookies"], {"session_name": "abc123"})


# Real field names confirmed against the live page — different from the
# draft Top-300's rows (rank/posRank here, not etrRank/posRankEtr, and no
# adp), plus a 'site' field distinguishing the two formats mixed together
# in one payload.
FAKE_ROS_ROWS = [
    {"player": "Jahmyr Gibbs", "position": "rb", "team": "det", "rank": 1, "posRank": "RB01", "site": "Half-PPR (1-QB)"},
    {"player": "Josh Allen", "position": "qb", "team": "buf", "rank": 33, "posRank": "QB01", "site": "Half-PPR (1-QB)"},
    {"player": "No Rank Guy", "position": "wr", "team": "nyj", "rank": None, "posRank": None, "site": "Half-PPR (1-QB)"},
    {"player": "Jahmyr Gibbs", "position": "rb", "team": "det", "rank": 1, "posRank": "RB01", "site": "Half-PPR (2-QB)"},
    {"player": "Josh Allen", "position": "qb", "team": "buf", "rank": 2, "posRank": "QB01", "site": "Half-PPR (2-QB)"},
]


class TestGetRosRankings(unittest.TestCase):
    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_filters_to_the_requested_format_by_site_field(self, mock_get, mock_config):
        mock_config.return_value = {"cookie": "session_name=abc123", "ros_url": "https://example.invalid/ros"}
        mock_response = MagicMock()
        mock_response.content = make_page_html(FAKE_ROS_ROWS).encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_ros_rankings("half_ppr")

        # The unranked row and the superflex-only rows are excluded.
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["full_name"], "Jahmyr Gibbs")
        self.assertEqual(result[0]["rank"], 1)
        self.assertEqual(result[1]["full_name"], "Josh Allen")
        self.assertEqual(result[1]["rank"], 33)

    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_superflex_pulls_the_other_site_value_from_the_same_payload(self, mock_get, mock_config):
        mock_config.return_value = {"cookie": "session_name=abc123", "ros_url": "https://example.invalid/ros"}
        mock_response = MagicMock()
        mock_response.content = make_page_html(FAKE_ROS_ROWS).encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_ros_rankings("superflex")

        self.assertEqual(len(result), 2)
        josh_allen = next(r for r in result if r["full_name"] == "Josh Allen")
        self.assertEqual(josh_allen["rank"], 2)  # QB ranked much higher under superflex

        # One fetch covers both formats -- no separate URL/request needed.
        mock_get.assert_called_once()

    def test_rejects_unpublished_formats(self):
        with self.assertRaises(ValueError):
            rankings.get_ros_rankings("full_ppr")
        with self.assertRaises(ValueError):
            rankings.get_ros_rankings("non_ppr")


FAKE_WEEKLY_PAYLOAD = {
    "expert_id": "534",
    "type": "Weekly Half PPR",
    "players": [
        {
            "rank": "1",
            "pos_rank": "RB1",
            "player_name": "Saquon Barkley",
            "player_positions": "RB",
            "player_team_id": "PHI",
            "bye_week": "9",
            "opponent": "DAL",
        },
        {
            "rank": "",  # unranked -> filtered out
            "pos_rank": None,
            "player_name": "Unranked Guy",
            "player_positions": "RB",
            "player_team_id": "NYJ",
            "bye_week": "",
            "opponent": None,
        },
    ],
}


class TestGetWeeklyRankings(unittest.TestCase):
    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_parses_jsonp_and_filters_unranked(self, mock_get, mock_config):
        mock_config.return_value = {
            "weekly": {
                "base_url": "https://example.invalid/expert-rankings.php",
                "expert_id": "534",
            }
        }
        mock_response = MagicMock()
        mock_response.text = f"FPW.rankingsCB({json.dumps(FAKE_WEEKLY_PAYLOAD)})"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_weekly_rankings(season=2026, week=1, position="RB", scoring_format="half_ppr")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["full_name"], "Saquon Barkley")
        self.assertEqual(result[0]["position"], "RB")
        self.assertEqual(result[0]["nfl_team"], "PHI")
        self.assertEqual(result[0]["rank"], 1)
        self.assertEqual(result[0]["bye_week"], 9)
        self.assertEqual(result[0]["opponent"], "DAL")

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["id"], "534")
        self.assertEqual(kwargs["params"]["scoring"], "HALF")
        self.assertEqual(kwargs["params"]["type"], "WEEKLY")
        # No cookie forwarded — this endpoint is public.
        self.assertNotIn("cookies", kwargs)


def make_tier_page_html(paragraphs: list[str]) -> str:
    body = "".join(f'<p class="p1">{p}</p>' for p in paragraphs)
    return f"<html><body>{body}</body></html>"


class TestGetTiers(unittest.TestCase):
    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_parses_multi_bold_tag_tier(self, mock_get, mock_config):
        # Mirrors the real page: players split across separate <b> tags within one <p>.
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "tier_urls": {"QB": "https://example.invalid/qb-tiers"},
        }
        html_body = make_tier_page_html(
            [
                "<b>Tier 1: Josh Allen (QB1) &gt;</b> <b>Lamar Jackson (QB2)</b><b></b>",
                "First-tier quarterbacks score at elite levels.",  # analysis prose, not a tier header
            ]
        )
        mock_response = MagicMock()
        mock_response.content = html_body.encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_tiers("QB")

        self.assertEqual(
            result,
            [
                {"full_name": "Josh Allen", "tier": 1},
                {"full_name": "Lamar Jackson", "tier": 1},
            ],
        )

    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_skips_unpublished_tiers(self, mock_get, mock_config):
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "tier_urls": {"QB": "https://example.invalid/qb-tiers"},
        }
        html_body = make_tier_page_html(
            [
                "<b>Tier 1: Josh Allen (QB1)</b>",
                "<b>Tier 2:&nbsp;</b>",  # not yet published
            ]
        )
        mock_response = MagicMock()
        mock_response.content = html_body.encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_tiers("QB")

        self.assertEqual(result, [{"full_name": "Josh Allen", "tier": 1}])

    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_handles_bare_names_without_position_rank_suffix(self, mock_get, mock_config):
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "tier_urls": {"RB": "https://example.invalid/rb-tiers"},
        }
        html_body = make_tier_page_html(
            ["<b>Tier 12: Jordan James &gt; Kaytron Allen &gt; Jaydon Blue</b>"]
        )
        mock_response = MagicMock()
        mock_response.content = html_body.encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_tiers("RB")

        self.assertEqual(
            result,
            [
                {"full_name": "Jordan James", "tier": 12},
                {"full_name": "Kaytron Allen", "tier": 12},
                {"full_name": "Jaydon Blue", "tier": 12},
            ],
        )

    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_handles_comma_separated_tier(self, mock_get, mock_config):
        # A late/deep tier occasionally lists names comma-separated instead of
        # with the usual "&gt;" delimiter, with no position-rank suffix.
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "tier_urls": {"TE": "https://example.invalid/te-tiers"},
        }
        html_body = make_tier_page_html(
            ["<b>Tier 7: Terrance Ferguson, Oronde Gadsden II, Cade Otton</b>"]
        )
        mock_response = MagicMock()
        mock_response.content = html_body.encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_tiers("TE")

        self.assertEqual(
            result,
            [
                {"full_name": "Terrance Ferguson", "tier": 7},
                {"full_name": "Oronde Gadsden II", "tier": 7},
                {"full_name": "Cade Otton", "tier": 7},
            ],
        )


    @patch("ffassistant.connectors.rankings.get_rankings_config")
    @patch("ffassistant.connectors.rankings.requests.get")
    def test_repairs_leaked_cp1252_apostrophe(self, mock_get, mock_config):
        # Tier copy is occasionally pasted in from a Windows-1252 source, leaking
        # a raw 0x92 byte (right single quote) into an otherwise UTF-8 page. A
        # strict/replace UTF-8 decode turns that into U+FFFD, mangling the name
        # ("Dont'e Thornton" -> "Dont�e Thornton") so it never matches.
        mock_config.return_value = {
            "cookie": "session_name=abc123",
            "tier_urls": {"WR": "https://example.invalid/wr-tiers"},
        }
        html_body = make_tier_page_html(
            ["<b>Tier 4: Dont" + bytes([0x92]).decode("cp1252") + "e Thornton (WR40)</b>"]
        )
        mock_response = MagicMock()
        mock_response.content = html_body.encode("cp1252")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = rankings.get_tiers("WR")

        self.assertEqual(result, [{"full_name": "Dont’e Thornton", "tier": 4}])


if __name__ == "__main__":
    unittest.main()
