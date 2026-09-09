import unittest
from unittest.mock import MagicMock, patch

from scripts import refresh_in_season


class TestRefreshInSeasonCli(unittest.TestCase):
    @patch.object(refresh_in_season, "get_connection")
    @patch.object(refresh_in_season, "run_full_refresh")
    def test_forwards_season_and_week_and_exits_zero_on_success(self, mock_run, mock_get_connection):
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn
        mock_run.return_value = {"had_failure": False}

        exit_code = refresh_in_season.main(["--season", "2026", "--week", "3"])

        self.assertEqual(exit_code, 0)
        mock_run.assert_called_once_with(mock_conn, season=2026, week=3)

    @patch.object(refresh_in_season, "get_connection")
    @patch.object(refresh_in_season, "run_full_refresh")
    def test_exits_nonzero_when_summary_reports_failure(self, mock_run, mock_get_connection):
        mock_get_connection.return_value = MagicMock()
        mock_run.return_value = {"had_failure": True}

        exit_code = refresh_in_season.main(["--season", "2026"])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
