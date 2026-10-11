import { api } from "./api.js";
import { positionColor } from "./positions.js";

// Re-fetch while the tab stays open. Every refresh is ~14 platform calls
// across all leagues plus one NFL scoreboard call; two minutes keeps that
// light while still feeling live on a Sunday.
const AUTO_REFRESH_MS = 2 * 60 * 1000;

let refreshTimer = null;

// Scoreboard: Keith's matchup in every active platform league at once — one
// card per league, horizontally scrollable like the Starters tab. Live data
// straight from each platform (see GET /api/scoreboard), nothing stored.
export async function renderScoreboardTab(container, state) {
  if (refreshTimer) clearInterval(refreshTimer);

  if (!state.week) {
    const prompt = el("p", "in-season-prompt");
    prompt.textContent = "Enter a week number above to see this week's live scoreboard.";
    container.appendChild(prompt);
    return;
  }

  const wrap = el("div", "in-season-view scoreboard");
  container.appendChild(wrap);

  const load = async () => {
    const data = await api.getScoreboard(state.season, state.week);
    wrap.replaceChildren(buildToolbar(data, load), ...buildBody(data));
  };
  await load();

  // Stops on its own once the tab is switched away (the wrap is detached on re-render).
  refreshTimer = setInterval(() => {
    if (!wrap.isConnected) {
      clearInterval(refreshTimer);
      refreshTimer = null;
      return;
    }
    load().catch(() => {});
  }, AUTO_REFRESH_MS);
}

function buildToolbar(data, load) {
  const bar = el("div", "scoreboard-toolbar");
  const button = el("button", "");
  button.type = "button";
  button.textContent = "Refresh";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Refreshing…";
    try {
      await load();
    } catch {
      button.disabled = false;
      button.textContent = "Refresh";
    }
  });
  bar.appendChild(button);

  const stamp = el("span", "rankings-sync-status");
  const time = new Date(data.fetched_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  stamp.textContent = `Updated ${time} · refreshes every 2 min`;
  bar.appendChild(stamp);
  return bar;
}

function buildBody(data) {
  const nodes = [];
  if (data.games_error) {
    const warn = el("p", "scoreboard-warning");
    warn.textContent = `Couldn't load NFL game status (${data.games_error}) — "playing now" and computed live projections are unavailable.`;
    nodes.push(warn);
  }
  if (data.matchups.length === 0) {
    const empty = el("span", "in-season-empty");
    empty.textContent = "No platform leagues with a team marked as yours yet — set it in League Settings.";
    nodes.push(empty);
    return nodes;
  }
  const scroll = el("div", "starters-all-scroll");
  for (const matchup of data.matchups) scroll.appendChild(buildCard(matchup));
  nodes.push(scroll);
  return nodes;
}

function buildCard(matchup) {
  const card = el("div", "starters-team-card scoreboard-card");
  const heading = document.createElement("h4");
  heading.textContent = matchup.league_name;
  card.appendChild(heading);

  if (matchup.error) {
    card.appendChild(note(`Couldn't load: ${matchup.error}`, "scoreboard-warning"));
    return card;
  }
  if (matchup.no_matchup) {
    card.appendChild(note("No head-to-head matchup this week.", "in-season-empty"));
    return card;
  }

  const { me, opponent } = matchup;
  const outlook = liveOutlook(me, opponent);
  if (outlook) card.classList.add(`scoreboard-${outlook}`);

  card.appendChild(buildSide(me, true));
  if (opponent) {
    card.appendChild(el("div", "scoreboard-divider"));
    card.appendChild(buildSide(opponent, false));
  } else {
    card.appendChild(note("Bye week — no opponent.", "in-season-empty"));
  }
  return card;
}

// "ahead"/"behind" by live projection, the best single read on how a matchup
// is going mid-slate. Nothing when either side has no live projection.
function liveOutlook(me, opponent) {
  if (!opponent || me.live_projected == null || opponent.live_projected == null) return null;
  if (me.live_projected === opponent.live_projected) return null;
  return me.live_projected > opponent.live_projected ? "ahead" : "behind";
}

function buildSide(side, isMine) {
  const block = el("div", "scoreboard-side" + (isMine ? " scoreboard-side-mine" : ""));

  const top = el("div", "scoreboard-side-top");
  const name = el("span", "scoreboard-team-name");
  name.textContent = side.team_name;
  top.appendChild(name);
  const score = el("span", "scoreboard-score");
  score.textContent = fmt(side.score);
  top.appendChild(score);
  block.appendChild(top);

  // One line under the name/score row: player counts under the team name,
  // projections right-aligned under the score.
  const sub = el("div", "scoreboard-side-sub");
  const counts = el("span", "scoreboard-counts");
  counts.textContent = `${side.playing_now.length} playing · ${side.yet_to_play} to play · ${side.done} done`;
  sub.appendChild(counts);

  const proj = el("span", "scoreboard-proj");
  proj.appendChild(document.createTextNode(`Proj ${fmt(side.projected)} · Live `));
  const live = el("span", `scoreboard-live ${liveTrendClass(side)}`);
  live.textContent = fmt(side.live_projected);
  if (side.live_projected == null) {
    live.title = "This platform doesn't send a live projection.";
  }
  proj.appendChild(live);
  sub.appendChild(proj);
  block.appendChild(sub);

  if (side.playing_now.length > 0) {
    const list = el("ul", "scoreboard-playing");
    for (const player of side.playing_now) list.appendChild(buildPlayer(player));
    block.appendChild(list);
  }
  return block;
}

// Green when the live projection is above the original, red when below — like
// the platform apps. Compared at the one decimal shown, so a pre-game
// 124.0 vs 123.97 rounding wobble doesn't show as red.
function liveTrendClass(side) {
  if (side.live_projected == null || side.projected == null) return "";
  const live = Number(fmt(side.live_projected));
  const original = Number(fmt(side.projected));
  if (live > original) return "scoreboard-live-up";
  if (live < original) return "scoreboard-live-down";
  return "";
}

function buildPlayer(player) {
  const li = el("li", "scoreboard-player");
  const chip = el("span", "position-chip");
  chip.textContent = player.position ?? "?";
  if (player.position) chip.style.backgroundColor = positionColor(player.position);
  li.appendChild(chip);

  const name = el("span", "scoreboard-player-name");
  name.textContent = player.full_name;
  li.appendChild(name);

  const pts = el("span", "scoreboard-player-points");
  pts.textContent = fmt(player.points);
  if (player.game_detail) pts.title = `${player.nfl_team ?? ""} · ${player.game_detail}`;
  li.appendChild(pts);
  return li;
}

function fmt(value) {
  return value == null ? "—" : Number(value).toFixed(1);
}

function note(text, className) {
  const p = el("p", className);
  p.textContent = text;
  return p;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
