"""Optimal weekly starting-lineup computation for the in-season Starters tab.

Pure function, no DB access — callers (ffassistant.api.in_season) gather the
roster/rankings data and pass it in, which keeps the assignment logic itself
unit-testable without a database.
"""

DEDICATED_POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPERFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}


def compute_starters(roster_slots: dict, players: list[dict]) -> dict:
    """roster_slots: {slot_name: count}, e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1,
    "FLEX": 1, "SUPER_FLEX": 1, "DST": 1, "K": 1, "BENCH": 6}. BENCH/IR and any
    unrecognized slot names are ignored — only starting slots go through assignment.

    players: one dict per rostered player — player_id, full_name, position, rank
    (this position's own weekly rank, or None), flex_rank (RB/WR/TE combined rank,
    or None), op_rank (QB/RB/WR/TE combined rank, or None), status.

    Fills dedicated position slots first (best players at that exact position, by
    that position's own weekly rank), then FLEX from whatever RB/WR/TE is left
    over (by the combined flex rank), then SUPER_FLEX from whatever QB/RB/WR/TE is
    left over (by the combined "OP" rank) — mirroring how a person fills out a
    lineup card top-to-bottom, skipping players already used above. Unranked
    players sort last (never excluded) — same convention as the Weekly view.

    Bench is sorted "closest to usable" first: each bench player's best rank
    among whichever lists actually matter in this league (their own position,
    plus flex_rank/op_rank only if this league actually has a FLEX/SUPER_FLEX
    slot to use them in) — the smaller that number, the less it'd take for them
    to crack the lineup. Players with no rank in any applicable list sort last.

    Returns {"slots": [{"slot_name", "player" | None}, ...], "bench": [players]}.
    """
    remaining = list(players)
    slots = []

    def take_best(pool, key):
        if not pool:
            return None
        return min(pool, key=lambda p: (p[key] is None, p[key]))

    for position in DEDICATED_POSITIONS:
        for _ in range(roster_slots.get(position, 0)):
            pool = [p for p in remaining if p["position"] == position]
            best = take_best(pool, "rank")
            slots.append({"slot_name": position, "player": best})
            if best is not None:
                remaining.remove(best)

    for _ in range(roster_slots.get("FLEX", 0)):
        pool = [p for p in remaining if p["position"] in FLEX_ELIGIBLE]
        best = take_best(pool, "flex_rank")
        slots.append({"slot_name": "FLEX", "player": best})
        if best is not None:
            remaining.remove(best)

    for _ in range(roster_slots.get("SUPER_FLEX", 0)):
        pool = [p for p in remaining if p["position"] in SUPERFLEX_ELIGIBLE]
        best = take_best(pool, "op_rank")
        slots.append({"slot_name": "SUPER_FLEX", "player": best})
        if best is not None:
            remaining.remove(best)

    def bench_sort_key(player):
        candidates = []
        if player["rank"] is not None:
            candidates.append(player["rank"])
        if (
            roster_slots.get("FLEX", 0) > 0
            and player["position"] in FLEX_ELIGIBLE
            and player.get("flex_rank") is not None
        ):
            candidates.append(player["flex_rank"])
        if (
            roster_slots.get("SUPER_FLEX", 0) > 0
            and player["position"] in SUPERFLEX_ELIGIBLE
            and player.get("op_rank") is not None
        ):
            candidates.append(player["op_rank"])
        return (1, 0) if not candidates else (0, min(candidates))

    bench = sorted(remaining, key=bench_sort_key)

    return {"slots": slots, "bench": bench}
