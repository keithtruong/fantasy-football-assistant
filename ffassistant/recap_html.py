"""Renders ffassistant.recap_data.gather_recap_data's output as a single,
self-contained HTML page — the actual weekly recap Keith reads, emails, and
posts a link to in GroupMe.

Written in the "TAMS Fantasybot" persona (old-school AI-generated tone,
puns throughout) — carried over from the draft recap's "DraftBot 3000"
voice per Keith's stated preference, renamed since this is a weekly recap,
not a draft tool. Colors/tokens mirror static/css/style.css's own
light/dark palette (position colors + gold/silver/bronze/steal/tough
semantic tokens) so this reads as part of the same app rather than a
bolted-on report, rather than inventing a new palette.

Pure function, no DB access — same three-layer split as the rest of this
feature: ffassistant.ingest.espn writes weekly_box_scores, ffassistant.recap
computes over it, ffassistant.recap_data gathers real rows from the DB, and
this module is the last, presentation-only step. Whatever
gather_recap_data() returned is exactly what render_recap_html() expects.
"""

import html

from ffassistant.recap import TIME_WINDOW_ORDER

POSITION_COLORS = {
    "QB": "#2f7d3c",
    "RB": "#2b5ea8",
    "WR": "#b23b3b",
    "TE": "#c65f9a",
    "DST": "#b8860b",
    "K": "#7449a6",
}
FALLBACK_COLOR = "#6b7280"
POSITION_ORDER = ("QB", "RB", "WR", "TE", "DST", "K")
POSITION_LABELS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "DST": "DEF", "K": "K"}  # DEF is fantasy-speak for DST
# Short axis labels for the per-matchup checkpoint chart — TIME_WINDOW_ORDER's
# names are narration-length, not axis-label-length.
WINDOW_LABELS = {
    "Thursday Night": "TNF",
    "Sunday Morning": "Sun AM",
    "Sunday Afternoon": "Sun PM",
    "Sunday Night": "SNF",
    "Monday Night": "MNF",
    "Other": "Other",
}

# One label per ffassistant.recap.next_week_preview tag — every tag a
# matchup earns gets its own badge, in this display order.
NEXT_WEEK_TAG_LABELS = {
    "top_seed_clash": "👑 Clash of the Titans (#1 vs #2)",
    "standings_battle": "📊 Standings Battle",
    "playoff_bubble": "🎯 Playoff Bubble",
    "high_scoring": "🔥 Potential Shootout",
    "sibling_matchup": "👨‍👦 Family Feud",
    "same_city": "🏙️ Local Rivalry",
}
NEXT_WEEK_TAG_ORDER = tuple(NEXT_WEEK_TAG_LABELS.keys())

BOT_NAME = "TAMS Fantasybot"


def _esc(value) -> str:
    return html.escape(str(value))


def _fmt(points) -> str:
    return f"{points:.1f}"


def _team_display(owner_name: str, real_name: str | None) -> str:
    """Real team name + owner nickname together, e.g. "Bijan'd meAt
    <span>(KB)</span>" — the shared display used everywhere a team appears
    with both names available (standings, matchup headers, Next Week
    Preview). Falls back to just the owner name when no real name is known
    (a league with no team_real_names data, or a team_id it doesn't cover).
    """
    owner_esc = _esc(owner_name)
    if not real_name:
        return owner_esc
    return f'{_esc(real_name)} <span class="owner-tag">({owner_esc})</span>'


def _position_chip(position: str) -> str:
    color = POSITION_COLORS.get(position, FALLBACK_COLOR)
    label = POSITION_LABELS.get(position, position)
    return f'<span class="pos-chip" style="background:{color}">{_esc(label)}</span>'


def _blowout_line(margin: float) -> str:
    if margin >= 60:
        return "an absolute massacre — someone's throwing their controller across the room"
    if margin >= 30:
        return "a proper beatdown"
    return "a comfortable, no-sweat cover"


def _nailbiter_line(margin: float) -> str:
    if margin < 1:
        return "closer than a coin flip — decided by less than a single point"
    if margin < 5:
        return "came down to the wire"
    return "stayed interesting all the way through"


def _efficiency_tier(pct) -> str:
    if pct is None:
        return "❓ No data"
    if pct >= 95:
        return "🎯 Lineup Perfection"
    if pct >= 85:
        return "✅ Pretty Solid"
    if pct >= 70:
        return "😬 Left Some On The Table"
    return "🔥 Self-Inflicted Disaster"


def _render_header(data: dict, league_name: str, bot_name: str) -> str:
    return f"""
    <header class="recap-header">
      <div class="bot-badge">🤖 {_esc(bot_name)}</div>
      <h1>{_esc(league_name)} — Week {data['week']} Recap</h1>
      <p class="tagline">Beep boop. I have processed your fantasy decisions. Some of you should feel bad.</p>
    </header>
    """


def _render_standings(data: dict) -> str:
    team_scores = data["team_scores"]
    if not team_scores:
        return _empty_section("This Week's Scores", "No box scores synced for this week yet.")

    rows = sorted(team_scores.items(), key=lambda kv: kv[1], reverse=True)
    high_low = data["high_low"]
    highest_id = high_low["highest"]["team_id"] if high_low["highest"] else None
    lowest_id = high_low["lowest"]["team_id"] if high_low["lowest"] else None

    team_real_names = data.get("team_real_names", {})
    body_rows = []
    for rank, (team_id, points) in enumerate(rows, start=1):
        team_name = _team_display(data["team_names"].get(team_id, f"Team {team_id}"), team_real_names.get(team_id))
        badge = ""
        if team_id == highest_id:
            badge = '<span class="award-badge gold">👑 Top Score</span>'
        elif team_id == lowest_id:
            badge = '<span class="award-badge tough">💩 Bottom of the Barrel</span>'
        body_rows.append(
            f"<tr><td class=\"rank-col\">{rank}</td><td>{team_name} {badge}</td>"
            f"<td class=\"num-col\">{_fmt(points)}</td></tr>"
        )

    return f"""
    <section class="recap-section">
      <h2>📊 This Week's Scores</h2>
      <table class="recap-table">
        <thead><tr><th></th><th>Team</th><th class="num-col">Points</th></tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </section>
    """


def _checkpoint_chart_svg(team_a_series: list[dict], team_b_series: list[dict], team_a_name: str, team_b_name: str) -> str:
    """Inline SVG line chart of cumulative points across the week's time
    windows for both sides of a matchup — no JS and no external chart
    library, so it survives both the hosted page and being pasted into an
    email client that strips <script>. Forward-fills a team's cumulative
    total through any window it had nobody active in, so a bye-window in
    the data reads as a flat stretch rather than a false drop back to zero.

    Returns "" (caller renders a text note instead) when there are fewer
    than two windows of data between both sides — not enough to draw a
    meaningful line. That's the expected state until box scores are synced
    with real game_date/projected_points values (see
    ffassistant.recap.score_by_checkpoint's docstring).
    """
    a_by_window = {row["window"]: row["cumulative_points"] for row in team_a_series}
    b_by_window = {row["window"]: row["cumulative_points"] for row in team_b_series}
    windows = [w for w in TIME_WINDOW_ORDER if w in a_by_window or w in b_by_window]
    if len(windows) < 2:
        return ""

    width, height = 600, 200
    pad_left, pad_right, pad_top, pad_bottom = 26, 26, 12, 28
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    n = len(windows)

    def fill_series(by_window: dict) -> list[float]:
        vals = []
        last = 0.0
        for w in windows:
            if w in by_window:
                last = by_window[w]
            vals.append(last)
        return vals

    a_vals = fill_series(a_by_window)
    b_vals = fill_series(b_by_window)
    max_val = max([*a_vals, *b_vals, 1.0])

    def x_at(i: int) -> float:
        return pad_left + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def points_attr(vals: list[float]) -> str:
        return " ".join(f"{x_at(i):.1f},{pad_top + plot_h - (plot_h * v / max_val):.1f}" for i, v in enumerate(vals))

    x_labels = "".join(
        f'<text x="{x_at(i):.1f}" y="{height - 8}" class="chart-axis-label" text-anchor="middle">'
        f'{_esc(WINDOW_LABELS.get(w, w))}</text>'
        for i, w in enumerate(windows)
    )

    return f"""
    <svg class="checkpoint-chart" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
      <line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" class="chart-axis" />
      <polyline points="{points_attr(a_vals)}" class="chart-line-a" fill="none" />
      <polyline points="{points_attr(b_vals)}" class="chart-line-b" fill="none" />
      {x_labels}
    </svg>
    <div class="chart-legend">
      <span class="legend-item"><span class="legend-swatch legend-a"></span>{_esc(team_a_name)}</span>
      <span class="legend-item"><span class="legend-swatch legend-b"></span>{_esc(team_b_name)}</span>
    </div>
    """


def _matchup_side_detail(detail: dict, team_name: str, real_name: str | None = None) -> str:
    top_players = detail.get("top_players") or []
    top_items = "".join(
        f'<li>{_position_chip(p["position"])} {_esc(p["full_name"])} <span class="pts">{_fmt(p["points"])}</span></li>'
        for p in top_players
    )
    top_block = (
        f'<div class="side-subhead">🌟 Top Players</div><ul>{top_items}</ul>' if top_players else ""
    )

    surprises = detail.get("performance_vs_projection") or []
    surprise_items = "".join(
        f'<li class="surprise-{p["tag"]}">{_esc(p["full_name"])} '
        f'{"went off for" if p["tag"] == "over" else "no-showed at"} {_fmt(p["points"])} '
        f'(projected {_fmt(p["projected_points"])})</li>'
        for p in surprises
    )
    surprise_block = (
        f'<div class="side-subhead">😲 Surprises</div><ul>{surprise_items}</ul>' if surprises else ""
    )

    return f"""<div class="matchup-side">
      <div class="side-team-name">{_team_display(team_name, real_name)}</div>
      {top_block}
      {surprise_block}
    </div>"""


def _render_matchups(data: dict) -> str:
    details = data.get("matchup_details") or []
    if not details:
        return _empty_section(
            "Matchup Stories",
            "No matchup pairings synced for this week yet, so I can't tell you who played whom — just the raw scores above.",
        )

    biggest_blowout_idx = max(range(len(details)), key=lambda i: details[i]["margin"]) if len(details) > 1 else None
    team_real_names = data.get("team_real_names", {})

    inputs, labels, panels = [], [], []
    for i, m in enumerate(details):
        tab_id = f"matchup-tab-{i}"
        panel_id = f"matchup-panel-{i}"
        a, b = m["team_a"], m["team_b"]
        a_real_name = team_real_names.get(a["team_id"])
        b_real_name = team_real_names.get(b["team_id"])

        badges = ""
        if m.get("is_matchup_of_the_week"):
            badges += " ⭐"
        if i == biggest_blowout_idx:
            badges += " 💥"

        inputs.append(
            f'<input type="radio" name="matchup-tabs" id="{tab_id}" class="matchup-tab-input" '
            f'{"checked" if i == 0 else ""}>'
        )
        labels.append(
            f'<label for="{tab_id}" class="matchup-tab-label">{_esc(a["team_name"])} vs {_esc(b["team_name"])}{badges}</label>'
        )

        flavor = _blowout_line(m["margin"]) if m["margin"] >= 20 else _nailbiter_line(m["margin"])
        chart = _checkpoint_chart_svg(
            m["team_a_detail"]["score_by_checkpoint"],
            m["team_b_detail"]["score_by_checkpoint"],
            a["team_name"],
            b["team_name"],
        )
        chart_block = chart or '<p class="section-note">Not enough game-time data synced yet to chart this one.</p>'
        narrative = m.get("narrative")
        headline = m.get("narrative_headline")
        headline_block = f'<h3 class="matchup-headline">{_esc(headline)}</h3>' if headline else ""
        narrative_block = f'{headline_block}<p class="matchup-narrative">{_esc(narrative)}</p>' if narrative else ""

        panels.append(
            f"""<div class="matchup-panel" id="{panel_id}">
              <div class="matchup-panel-score">
                <strong>{_team_display(a['team_name'], a_real_name)}</strong> {_fmt(a['points'])} — {_fmt(b['points'])} <strong>{_team_display(b['team_name'], b_real_name)}</strong>
                <div class="flavor">Decided by {_fmt(m['margin'])} points — {flavor}.</div>
              </div>
              {narrative_block}
              {chart_block}
              <div class="matchup-sides">
                {_matchup_side_detail(m['team_a_detail'], a['team_name'], a_real_name)}
                {_matchup_side_detail(m['team_b_detail'], b['team_name'], b_real_name)}
              </div>
            </div>"""
        )

    # Both rules use the general-sibling combinator (~), matched by each tab's
    # own id, rather than the adjacent-sibling combinator (+) on class alone.
    # The DOM here is a flat run of all <input>s, then all <label>s, then all
    # panels (see the join order right below) — so a label is almost never
    # the checked input's *immediate* next sibling; a class-only "+" selector
    # would only ever match the wraparound case (last input -> first label),
    # which is exactly the "wrong tab lights up" bug this replaced.
    toggle_css = "".join(
        f'#matchup-tab-{i}:checked ~ #matchup-panel-{i} {{ display: block; }}'
        f'#matchup-tab-{i}:checked ~ label[for="matchup-tab-{i}"] {{ '
        f'background: var(--accent); color: #fff; border-color: var(--accent); }}'
        for i in range(len(details))
    )

    return f"""
    <section class="recap-section matchup-tabs-section">
      <h2>🏟️ Matchup Stories</h2>
      <p class="section-note">Matchup of the week (⭐ closest game) shown first. 💥 marks the week's biggest blowout.</p>
      <style>{toggle_css}</style>
      <div class="matchup-tabs">
        {''.join(inputs)}
        {''.join(labels)}
        {''.join(panels)}
      </div>
    </section>
    """


def _render_top_performers(data: dict) -> str:
    top_performers = data["top_performers"]
    if not top_performers:
        return _empty_section("Top Performers", "No box scores synced for this week yet.")

    blocks = []
    for position in POSITION_ORDER:
        players = top_performers.get(position)
        if not players:
            continue
        items = "".join(
            f'<li><span class="perf-name"><span class="rank-num">#{i}</span> {_esc(p["full_name"])} '
            f'<span class="team-tag">({_esc(p.get("team_name", ""))})</span></span>'
            f'<span class="pts">{_fmt(p["points"])} pts</span></li>'
            for i, p in enumerate(players, start=1)
        )
        blocks.append(f'<div class="perf-block">{_position_chip(position)}<ul>{items}</ul></div>')

    return f"""
    <section class="recap-section">
      <h2>⭐ Top Performers</h2>
      <div class="perf-grid">{''.join(blocks)}</div>
    </section>
    """


def _render_best_by_slot(data: dict) -> str:
    best_by_slot = data["best_by_slot"]
    if not best_by_slot or all(v is None for v in best_by_slot.values()):
        return _empty_section("Superlative Awards", "No box scores synced for this week yet.")

    cards = []
    for slot in (*POSITION_ORDER, "BENCH"):
        info = best_by_slot.get(slot)
        if info is None:
            continue
        label = "Best Bench" if slot == "BENCH" else f"Best {POSITION_LABELS.get(slot, slot)} Output"
        chip = '<span class="pos-chip" style="background:#6b7280">BN</span>' if slot == "BENCH" else _position_chip(slot)
        color = POSITION_COLORS.get(slot, FALLBACK_COLOR) if slot != "BENCH" else FALLBACK_COLOR
        contributors = info.get("players") or []
        contributor_names = "<br>".join(f"{_esc(p['full_name'])} ({_fmt(p['points'])})" for p in contributors)
        contributor_line = f'<div class="award-contributors">{contributor_names}</div>' if contributors else ""
        cards.append(
            f"""<div class="award-card">
              {chip}
              <div class="award-label">{_esc(label)}</div>
              <div class="award-team">{_esc(info['team_name'])}</div>
              <div class="award-points" style="color:{color}">{_fmt(info['points'])} pts</div>
              {contributor_line}
            </div>"""
        )

    return f"""
    <section class="recap-section">
      <h2>🏆 Superlative Awards</h2>
      <div class="award-grid">{''.join(cards)}</div>
    </section>
    """


def _render_optimal_lineup(data: dict) -> str:
    optimal_by_team = data["optimal_lineup_by_team"]
    if not optimal_by_team:
        return _empty_section("Lineup Efficiency Report Card", "No box scores synced for this week yet.")

    rows = sorted(optimal_by_team.items(), key=lambda kv: (kv[1]["pct"] is None, -(kv[1]["pct"] or 0)))
    body_rows = []
    for team_id, result in rows:
        team_name = _esc(data["team_names"].get(team_id, f"Team {team_id}"))
        pct = result["pct"]
        pct_str = f"{pct:.1f}%" if pct is not None else "—"
        body_rows.append(
            f"<tr><td>{team_name}</td><td class=\"num-col\">{_fmt(result['actual_points'])}</td>"
            f"<td class=\"num-col\">{_fmt(result['optimal_points'])}</td>"
            f"<td class=\"num-col\">{pct_str}</td><td>{_efficiency_tier(pct)}</td></tr>"
        )

    return f"""
    <section class="recap-section">
      <h2>🧠 Lineup Efficiency Report Card</h2>
      <p class="section-note">What you actually started vs. the best possible lineup your own roster could have produced, with the benefit of hindsight I definitely did not have before kickoff.</p>
      <table class="recap-table">
        <thead><tr><th>Team</th><th class="num-col">Started</th><th class="num-col">Best Possible</th><th class="num-col">Efficiency</th><th>Verdict</th></tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </section>
    """


def _render_gaffes(data: dict) -> str:
    gaffes_by_team = data["gaffes_by_team"]
    all_gaffes = []
    for team_id, gaffes in gaffes_by_team.items():
        for g in gaffes:
            all_gaffes.append({**g, "team_name": data["team_names"].get(team_id, f"Team {team_id}")})

    if not all_gaffes:
        return _empty_section(
            "🍆 Boners of the Week", "Nobody made a start/sit mistake this week — either great decisions, or great luck."
        )

    worst = sorted(all_gaffes, key=lambda g: g["missed_points"], reverse=True)[:5]
    items = "".join(
        f"""<li>
          <strong>{_esc(g['team_name'])}</strong> started
          <strong>{_esc(g['started']['full_name'])}</strong> ({_fmt(g['started']['points'])} pts) over
          <strong>{_esc(g['benched']['full_name'])}</strong> ({_fmt(g['benched']['points'])} pts) —
          <span class="missed">{_fmt(g['missed_points'])} points</span> left on the table.
        </li>"""
        for g in worst
    )

    return f"""
    <section class="recap-section">
      <h2>🍆 Boners of the Week</h2>
      <ul class="gaffe-list">{items}</ul>
    </section>
    """


def _render_waiver_wire(data: dict) -> str:
    waiver_wire = data.get("waiver_wire") or []
    if not waiver_wire:
        if data.get("waiver_wire_synced"):
            return _empty_section(
                "Waiver Wire Watch",
                "Nobody among this week's free agents beat their own projection by enough to "
                "have cracked a starting lineup — either great rosters, or a quiet week for "
                "free agents.",
            )
        return _empty_section(
            "Waiver Wire Watch",
            "Nobody's synced this week's free-agent scores yet — this section needs "
            "weekly_free_agent_scores populated for this week before I can tell you who "
            "you should have picked up. (Only ever possible for the current season — ESPN "
            "won't serve a free-agent pool for an old, completed one.)",
        )

    items = "".join(
        f"""<li>
          {_position_chip(p['position'])}
          <strong>{_esc(p['full_name'])}</strong> put up <strong>{_fmt(p['points'])} pts</strong>
          (projected {_fmt(p['projected_points'])}).
        </li>"""
        for p in waiver_wire
    )

    return f"""
    <section class="recap-section">
      <h2>🕵️ Waiver Wire Watch</h2>
      <p class="section-note">Nobody in the league rostered these guys — one per position, each good enough to have cracked a starting lineup.</p>
      <ul class="waiver-list">{items}</ul>
    </section>
    """


def _fmt_record(team: dict) -> str:
    wins, losses, ties = team.get("wins"), team.get("losses"), team.get("ties")
    if wins is None or losses is None:
        return "—"
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def _render_standings_table(data: dict) -> str:
    standings = data.get("standings") or []
    if not standings:
        return '<p class="section-note">No standings synced for this league yet.</p>'

    rows = "".join(
        f"""<tr>
          <td class="rank-col">{t['rank']}</td>
          <td>{_team_display(t['team_name'], t.get('team_real_name'))}</td>
          <td class="num-col">{_esc(_fmt_record(t))}</td>
          <td class="num-col">{_fmt(t['points_for']) if t.get('points_for') is not None else '—'}</td>
          <td class="num-col">{f"{t['playoff_pct']:.0f}%" if t.get('playoff_pct') is not None else '—'}</td>
        </tr>"""
        for t in standings
    )
    return f"""
    <table class="recap-table">
      <thead><tr><th></th><th>Team</th><th class="num-col">Record</th><th class="num-col">PF</th><th class="num-col">Playoff %</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _render_next_week_matchups(data: dict) -> str:
    next_week = data.get("next_week") or {}
    matchups = next_week.get("matchups") or []
    if not matchups:
        return (
            '<p class="section-note">Next week\'s matchup pairings haven\'t been synced yet — '
            "once they are, this is where the matchups worth watching show up.</p>"
        )

    cards = []
    for m in matchups:
        a, b = m["team_a"], m["team_b"]
        badges = "".join(
            f'<span class="nw-tag">{NEXT_WEEK_TAG_LABELS[tag]}</span>' for tag in NEXT_WEEK_TAG_ORDER if tag in m["tags"]
        )
        badges_block = f'<div class="nw-tags">{badges}</div>' if badges else ""

        def side_line(side: dict) -> str:
            proj = f" · proj. {_fmt(side['projected_score'])}" if side.get("projected_score") is not None else ""
            record = f" ({_esc(_fmt_record(side))})" if side.get("wins") is not None else ""
            rank = f"#{side['rank']} " if side.get("rank") is not None else ""
            team = _team_display(side.get("team_name", "Unknown"), side.get("team_real_name"))
            return f"{rank}<strong>{team}</strong>{record}{proj}"

        cards.append(
            f"""<div class="nw-card">
              <div class="nw-matchup">{side_line(a)} <span class="nw-vs">vs</span> {side_line(b)}</div>
              {badges_block}
            </div>"""
        )

    return f'<div class="nw-grid">{"".join(cards)}</div>'


def _render_next_week_preview(data: dict) -> str:
    next_week = data.get("next_week") or {}
    week_num = next_week.get("week")
    heading = f"🔮 Week {week_num} Preview" if week_num is not None else "🔮 Next Week Preview"

    return f"""
    <section class="recap-section">
      <h2>{_esc(heading)}</h2>
      <p class="section-note">Updated standings, then next week's matchups worth circling — close in the standings, playoff stakes on the line, or a projected shootout.</p>
      {_render_standings_table(data)}
      {_render_next_week_matchups(data)}
    </section>
    """


def _empty_section(title: str, note: str) -> str:
    return f"""
    <section class="recap-section">
      <h2>{_esc(title)}</h2>
      <p class="section-note">{_esc(note)}</p>
    </section>
    """


def render_recap_html(data: dict, league_name: str = "Fantasy League", bot_name: str = BOT_NAME) -> str:
    """Renders the full recap page from ffassistant.recap_data.gather_recap_data's
    output. `league_name` isn't part of that dict (it's a leagues.name lookup
    the caller already has), so it's passed separately. `bot_name` defaults to
    the BOT_NAME placeholder above — pass an override once the rename is decided.
    """
    sections = "".join(
        [
            _render_standings(data),
            _render_matchups(data),
            _render_top_performers(data),
            _render_best_by_slot(data),
            _render_optimal_lineup(data),
            _render_gaffes(data),
            _render_waiver_wire(data),
            _render_next_week_preview(data),
        ]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(league_name)} — Week {data['week']} Recap</title>
<style>
:root {{
  --bg: #f4f5f2; --surface: #ffffff; --ink-strong: #1a1e1a; --ink: #1a1e1a;
  --ink-muted: #5b6359; --line: #d9ddd4; --accent: #2e4b6b; --filled: #e3f1e8;
  --highlight: #fff4d9; --steal: #2f7d52; --tough: #f6dbdb; --tough-ink: #a13a3a;
  --gold-bg: #fbe8a6; --gold-ink: #7a5b00; --silver-bg: #e2e5e9; --silver-ink: #4a4f57;
  --bronze-bg: #eecfae; --bronze-ink: #7a431a;
  color-scheme: light;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0f1923; --surface: #0a1319; --ink-strong: #f5efe6; --ink: #c8bfb5;
    --ink-muted: #7a8694; --line: #1d2d3a; --accent: #c95e3a; --filled: #16241c;
    --highlight: #2a2013; --steal: #5fae82; --tough: #3a1c1c; --tough-ink: #e2938c;
    --gold-bg: #4a3b12; --gold-ink: #f0d060; --silver-bg: #33383f; --silver-ink: #d3d7dc;
    --bronze-bg: #3d2712; --bronze-ink: #dda06a;
    color-scheme: dark;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0 16px 60px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--ink);
}}
.recap-header {{
  max-width: 760px; margin: 0 auto; padding: 28px 0 16px; text-align: center;
}}
.bot-badge {{
  display: inline-block; background: var(--accent); color: #fff; border-radius: 999px;
  padding: 4px 14px; font-size: 12.5px; font-weight: 700; letter-spacing: 0.02em; margin-bottom: 10px;
}}
.recap-header h1 {{ margin: 0 0 6px; font-size: 26px; color: var(--ink-strong); }}
.tagline {{ margin: 0; color: var(--ink-muted); font-size: 14px; font-style: italic; }}
.recap-section {{
  max-width: 760px; margin: 0 auto 22px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 8px; padding: 18px 20px;
}}
.recap-section h2 {{ margin: 0 0 16px; font-size: 17px; color: var(--accent); }}
.section-note {{ margin: 0 0 14px; color: var(--ink-muted); font-size: 13.5px; }}
table.recap-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
table.recap-table th {{
  text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--ink-muted); padding: 6px 8px; border-bottom: 1px solid var(--line);
}}
table.recap-table td {{ padding: 7px 8px; border-bottom: 1px solid var(--line); }}
.num-col {{ text-align: right; font-variant-numeric: tabular-nums; }}
.rank-col {{ color: var(--ink-muted); width: 20px; }}
.award-badge {{ border-radius: 999px; padding: 2px 9px; font-size: 11px; font-weight: 700; margin-left: 6px; }}
.award-badge.gold {{ background: var(--gold-bg); color: var(--gold-ink); }}
.award-badge.tough {{ background: var(--tough); color: var(--tough-ink); }}
.pos-chip {{
  display: inline-block; color: #fff; border-radius: 999px; padding: 2px 10px;
  font-size: 11.5px; font-weight: 700;
}}
.matchup-grid, .perf-grid, .award-grid {{ display: flex; flex-wrap: wrap; gap: 14px; }}
.matchup-card, .award-card, .perf-block {{
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; flex: 1 1 220px;
}}
.matchup-card h3 {{ margin: 0 0 6px; font-size: 14px; color: var(--ink-strong); }}
.matchup-card p {{ margin: 4px 0; font-size: 14px; }}
.flavor {{ color: var(--ink-muted); font-size: 12.5px; font-style: italic; }}
.perf-block ul {{ list-style: none; margin: 8px 0 0; padding: 0; font-size: 13.5px; }}
.perf-block li {{
  display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 3px 0;
}}
.perf-name {{ min-width: 0; }}
.rank-num {{ color: var(--ink-muted); font-size: 11.5px; margin-right: 4px; }}
.team-tag {{ color: var(--ink-muted); font-size: 12px; }}
.owner-tag {{ color: var(--accent); font-size: 13px; font-weight: 400; }}
.pts {{ flex: 0 0 auto; white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 600; }}
.award-card {{ text-align: center; flex: 1 1 150px; }}
.award-label {{ font-size: 11.5px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.02em; margin-top: 8px; }}
.award-team {{ font-size: 15px; font-weight: 700; color: var(--ink-strong); margin-top: 2px; }}
.award-points {{ font-size: 19px; font-weight: 800; margin-top: 2px; }}
.award-contributors {{ font-size: 11.5px; color: var(--ink-muted); margin-top: 6px; line-height: 1.6; }}
ul.gaffe-list {{ margin: 0; padding-left: 20px; font-size: 14px; }}
ul.gaffe-list li {{ margin-bottom: 10px; }}
.missed {{ background: var(--tough); color: var(--tough-ink); border-radius: 999px; padding: 1px 8px; font-weight: 700; }}
ul.waiver-list {{ margin: 0; padding-left: 20px; font-size: 14px; }}
ul.waiver-list li {{ margin-bottom: 10px; }}
.matchup-tabs {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.matchup-tab-input {{ display: none; }}
.matchup-tab-label {{
  cursor: pointer; padding: 6px 13px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--bg); font-size: 12.5px; font-weight: 600; color: var(--ink-muted); user-select: none;
}}
/* Per-tab highlight rules are generated alongside the panel-toggle rules
   in _render_matchups' toggle_css — see that function's comment for why a
   plain ":checked + .matchup-tab-label" rule doesn't work here. */
.matchup-panel {{ display: none; flex-basis: 100%; margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }}
.matchup-panel-score {{ font-size: 16px; }}
.matchup-headline {{
  font-size: 15px; font-weight: 700; color: var(--accent); margin: 14px 0 0 0;
}}
.matchup-narrative {{
  font-size: 13.5px; font-style: italic; color: var(--ink); background: var(--bg);
  border-left: 3px solid var(--accent); padding: 8px 12px; margin: 10px 0 10px 0; border-radius: 0 4px 4px 0;
}}
.checkpoint-chart {{ width: 100%; height: auto; margin-top: 8px; display: block; }}
.chart-axis {{ stroke: var(--line); stroke-width: 1; }}
.chart-line-a {{ stroke: var(--accent); stroke-width: 2.5; }}
.chart-line-b {{ stroke: #1f9e8a; stroke-width: 2.5; }}
.chart-axis-label {{ fill: var(--ink-muted); font-size: 9px; }}
.chart-legend {{ display: flex; gap: 16px; font-size: 12px; color: var(--ink-muted); margin-top: 2px; }}
.legend-swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
.legend-a {{ background: var(--accent); }}
.legend-b {{ background: #1f9e8a; }}
.matchup-sides {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 14px; }}
.matchup-side {{ flex: 1 1 220px; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; }}
.side-team-name {{ font-weight: 700; font-size: 14px; }}
.side-subhead {{
  font-size: 12.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--accent); margin-top: 12px; padding-bottom: 4px; border-bottom: 2px solid var(--accent);
}}
.matchup-side ul {{ list-style: none; margin: 8px 0 0; padding: 0; font-size: 13px; }}
.matchup-side li {{ display: flex; align-items: center; gap: 6px; padding: 2px 0; }}
.matchup-side .pts {{ margin-left: auto; font-weight: 600; font-variant-numeric: tabular-nums; }}
.surprise-over {{ color: var(--steal); }}
.surprise-under {{ color: var(--tough-ink); }}
.nw-grid {{ display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }}
.nw-card {{ background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 10px 14px; }}
.nw-matchup {{ font-size: 14px; }}
.nw-vs {{ color: var(--ink-muted); font-size: 12px; margin: 0 6px; }}
.nw-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
.nw-tag {{
  display: inline-block; background: var(--highlight); border-radius: 999px; padding: 2px 10px;
  font-size: 11.5px; font-weight: 600; color: var(--ink);
}}
</style>
</head>
<body>
{_render_header(data, league_name, bot_name)}
{sections}
</body>
</html>
"""
