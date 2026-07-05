"""Pure snake-draft order math — no DB, no Flask, easy to unit test in isolation."""


def compute_pick_slot(pick_number: int, team_count: int) -> tuple[int, int]:
    """Returns (round, draft_position) for a given overall pick_number in a snake draft.

    Round 1 goes draft_position 1..N, round 2 reverses N..1, round 3 forward again, etc.
    """
    round_num = (pick_number - 1) // team_count + 1
    index_in_round = (pick_number - 1) % team_count  # 0-indexed
    if round_num % 2 == 1:
        draft_position = index_in_round + 1
    else:
        draft_position = team_count - index_in_round
    return round_num, draft_position
