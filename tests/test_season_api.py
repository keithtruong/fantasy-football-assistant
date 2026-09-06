from tests.test_api import ApiTestCase


class TestSeasonApi(ApiTestCase):
    def test_get_before_anything_set(self):
        resp = self.client.get("/api/season/2026")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNone(data["week1_start_date"])
        self.assertIsNone(data["current_week"])

    def test_put_then_get_round_trips(self):
        resp = self.client.put("/api/season/2026", json={"week1_start_date": "2026-09-09"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["week1_start_date"], "2026-09-09")

        resp = self.client.get("/api/season/2026")
        self.assertEqual(resp.get_json()["week1_start_date"], "2026-09-09")

    def test_put_missing_date_is_400(self):
        resp = self.client.put("/api/season/2026", json={})
        self.assertEqual(resp.status_code, 400)

    def test_put_bad_date_format_is_400(self):
        resp = self.client.put("/api/season/2026", json={"week1_start_date": "09/09/2026"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    import unittest

    unittest.main()
