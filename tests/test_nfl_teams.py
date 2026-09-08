import unittest

from ffassistant.nfl_teams import canonical_team_code


class TestCanonicalTeamCode(unittest.TestCase):
    def test_washington_spellings_all_collapse_to_wsh(self):
        for raw in ("WAS", "was", "Was", " WAS ", "WSH", "wsh"):
            self.assertEqual(canonical_team_code(raw), "WSH", raw)

    def test_rams_provider_code_maps_to_lar(self):
        self.assertEqual(canonical_team_code("LA"), "LAR")
        self.assertEqual(canonical_team_code("LAR"), "LAR")

    def test_relocated_team_legacy_codes(self):
        self.assertEqual(canonical_team_code("STL"), "LAR")
        self.assertEqual(canonical_team_code("SD"), "LAC")
        self.assertEqual(canonical_team_code("OAK"), "LV")

    def test_alternate_codes(self):
        self.assertEqual(canonical_team_code("JAC"), "JAX")
        self.assertEqual(canonical_team_code("ARZ"), "ARI")

    def test_title_case_from_yahoo_is_upper_cased(self):
        self.assertEqual(canonical_team_code("Bal"), "BAL")
        self.assertEqual(canonical_team_code("Sea"), "SEA")

    def test_non_team_values_become_none(self):
        for raw in (None, "", "  ", "FA", "None", "none", "NULL", "0"):
            self.assertIsNone(canonical_team_code(raw), raw)

    def test_unknown_code_passes_through_upper_cased(self):
        # A future relocation/expansion team lands somewhere sensible rather
        # than being silently dropped.
        self.assertEqual(canonical_team_code("xyz"), "XYZ")

    def test_already_canonical_codes_untouched(self):
        for code in ("KC", "GB", "NE", "NO", "SF", "TB", "LV", "JAX", "ARI"):
            self.assertEqual(canonical_team_code(code), code)


if __name__ == "__main__":
    unittest.main()
