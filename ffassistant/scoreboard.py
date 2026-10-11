"""Live Scoreboard logic — pure and DB-free, same split as starters.py and
trade_finder.py. The connectors fetch each side's live starters; this module
joins them to NFL game state and works out who's playing right now and what
each side's projection looks like.

Nothing here (or anywhere in the Scoreboard path) is written to the database:
live scores only matter while they're live, and W-L/recaps already keep the
final results. Keeping frequent Sunday refreshes away from SQLite also keeps
them clear of the mid-write locking issue described in CLAUDE.md.
"""

from ffassistant.nfl_teams import canonical_team_code

GAME_SECONDS = 60 * 60
QUARTER_SECONDS = 15 * 60


def parse_nfl_games(scoreboard: dict) -> dict:
    """{team_code: {state, detail, remaining_fraction}} from ESPN's public NFL
    scoreboard JSON (site.api.espn.com/.../nfl/scoreboard). `state` is ESPN's
    own 'pre' | 'in' | 'post'. `remaining_fraction` is the share of regulation
    still to play (1.0 before kickoff, 0.0 once final or in overtime) — used to
    pro-rate an in-progress player's projection. Both teams in a game get the
    same entry, keyed by canonical team code so it joins to every platform's
    starters regardless of how that platform spells the team.
    """
    games = {}
    for event in scoreboard.get("events", []):
        competition = event["competitions"][0]
        status = competition["status"]
        state = status["type"]["state"]
        if state == "pre":
            remaining = 1.0
        elif state == "post":
            remaining = 0.0
        else:
            period = status.get("period") or 1
            clock = status.get("clock") or 0
            remaining = max(0.0, min(1.0, ((4 - period) * QUARTER_SECONDS + clock) / GAME_SECONDS))
            if period > 4:
                remaining = 0.0
        entry = {"state": state, "detail": status["type"].get("shortDetail"), "remaining_fraction": remaining}
        for competitor in competition["competitors"]:
            code = canonical_team_code(competitor["team"]["abbreviation"])
            if code:
                games[code] = entry
    return games


def game_state(nfl_team: str | None, games: dict) -> str:
    """'pre' | 'in' | 'post', or 'none' for a free agent or a team on bye."""
    game = games.get(canonical_team_code(nfl_team)) if nfl_team else None
    return game["state"] if game else "none"


def computed_live_projection(starters: list[dict], games: dict) -> float | None:
    """Live projection for a side whose platform doesn't send one: actual
    points for finished games, the projection for games not started yet, and
    actual + the projection pro-rated by time left for games in progress.
    A starter with no projection counts as zero still to come. None if no
    starter has a projection at all — better to show nothing than a number
    that's really just the current score. Also None without NFL game state
    (the NFL scoreboard call failed), since every starter would otherwise
    look finished.
    """
    if not games or not any(p.get("projected") is not None for p in starters):
        return None
    total = 0.0
    for player in starters:
        points = player.get("points") or 0.0
        projected = player.get("projected") or 0.0
        game = games.get(canonical_team_code(player.get("nfl_team"))) if player.get("nfl_team") else None
        if game is None or game["state"] == "post":
            total += points
        elif game["state"] == "pre":
            total += projected
        else:
            total += points + projected * game["remaining_fraction"]
    return round(total, 2)


def build_side(side: dict, games: dict) -> dict:
    """One side of a matchup, ready for display. `side` comes from a
    connector's get_live_matchup: {platform_team_id, score, projected,
    live_projected, starters: [{full_name, position, nfl_team, slot, points,
    projected}]}. `projected`/`live_projected` are the platform's own team
    figures when it has them (None otherwise).

    Original projection falls back to the sum of starters' pre-game
    projections; live projection falls back to computed_live_projection.
    Starters are tagged with their game state and split into playing now /
    yet to play / done counts.
    """
    starters = []
    for player in side["starters"]:
        state = game_state(player.get("nfl_team"), games)
        game = games.get(canonical_team_code(player.get("nfl_team"))) if player.get("nfl_team") else None
        starters.append({**player, "game_state": state, "game_detail": game["detail"] if game else None})

    projected = side.get("projected")
    if projected is None and any(p.get("projected") is not None for p in starters):
        projected = round(sum(p.get("projected") or 0.0 for p in starters), 2)

    live_projected = side.get("live_projected")
    if live_projected is None:
        live_projected = computed_live_projection(starters, games)

    playing = [p for p in starters if p["game_state"] == "in"]
    playing.sort(key=lambda p: -(p.get("points") or 0.0))
    return {
        "platform_team_id": side["platform_team_id"],
        "score": side.get("score"),
        "projected": projected,
        "live_projected": live_projected,
        "playing_now": playing,
        "yet_to_play": sum(1 for p in starters if p["game_state"] == "pre"),
        "done": sum(1 for p in starters if p["game_state"] in ("post", "none")),
    }
