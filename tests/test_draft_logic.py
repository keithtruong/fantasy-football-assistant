import unittest

from ffassistant.draft_logic import compute_pick_slot


class TestComputePickSlot(unittest.TestCase):
    def test_round_one_is_forward_order(self):
        for pick_number in range(1, 11):
            round_num, draft_position = compute_pick_slot(pick_number, team_count=10)
            self.assertEqual(round_num, 1)
            self.assertEqual(draft_position, pick_number)

    def test_round_two_snakes_backward(self):
        self.assertEqual(compute_pick_slot(11, team_count=10), (2, 10))
        self.assertEqual(compute_pick_slot(15, team_count=10), (2, 6))
        self.assertEqual(compute_pick_slot(20, team_count=10), (2, 1))

    def test_round_three_forward_again(self):
        self.assertEqual(compute_pick_slot(21, team_count=10), (3, 1))
        self.assertEqual(compute_pick_slot(30, team_count=10), (3, 10))

    def test_small_league(self):
        self.assertEqual(compute_pick_slot(1, team_count=8), (1, 1))
        self.assertEqual(compute_pick_slot(8, team_count=8), (1, 8))
        self.assertEqual(compute_pick_slot(9, team_count=8), (2, 8))
        self.assertEqual(compute_pick_slot(16, team_count=8), (2, 1))


if __name__ == "__main__":
    unittest.main()
