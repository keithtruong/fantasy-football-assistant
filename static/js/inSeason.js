import { api } from "./api.js";
import { positionColor } from "./positions.js";
import { renderScheduleTab } from "./schedule.js";
import { renderStartersTab } from "./starters.js";

const WEEKLY_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];
const ROS_POSITIONS = ["QB", "RB", "WR", "TE"];

export async function renderInSeasonView(container, state) {
  const view = state.inSeasonTab; // "weekly" | "starters" | "ros" | "schedule"

  if (view === "schedule") {
    await renderScheduleTab(container, state);
    return;
  }

  if ((view === "weekly" || view === "starters") && !state.week) {
    const prompt = document.createElement("p");
    prompt.className = "in-season-prompt";
    prompt.textContent =
      view === "starters"
        ? "Enter a week number above to see this week's optimal starting lineup."
        : "Enter a week number above to see this week's rostered-vs-available breakdown.";
    container.appendChild(prompt);
    return;
  }

  if (view === "starters") {
    await renderStartersTab(container, state);
    return;
  }

  const positions = view === "weekly" ? WEEKLY_POSITIONS : ROS_POSITIONS;
  const data = await api.getInSeason(state.leagueId, view, state.season, view === "weekly" ? state.week : null);

  const wrap = el("div", "in-season-view");
  const generalInfo = buildGeneralInfo(data);
  if (generalInfo) wrap.appendChild(generalInfo);
  wrap.appendChild(buildColumnLabels());
  for (const position of positions) {
    wrap.appendChild(buildPositionSection(position, data[position]));
  }
  container.appendChild(wrap);
}

function formatRecord(record) {
  if (record.wins == null) return "record unknown";
  return record.ties ? `${record.wins}-${record.losses}-${record.ties}` : `${record.wins}-${record.losses}`;
}

// One card for everything that isn't a per-player rank: record, this week's
// opponent, waiver priority, and news on rostered players. Each line is
// omitted individually when unknown (not yet synced) rather than shown blank
// — and the whole card is skipped if nothing is known yet.
function buildGeneralInfo(data) {
  const hasRecord = data.record && data.record.wins != null;
  const hasAnything = hasRecord || data.opponent != null || data.waiver_priority != null || data.player_news.length > 0;
  if (!hasAnything) return null;

  const card = el("div", "in-season-info-card");
  const title = document.createElement("h3");
  title.textContent = "This Week";
  card.appendChild(title);

  if (hasRecord) {
    card.appendChild(buildInfoLine(`Your record: ${formatRecord(data.record)}`));
  }
  if (data.opponent) {
    card.appendChild(
      buildInfoLine(`Opponent: ${data.opponent.team_name} (${formatRecord(data.opponent)})`)
    );
  }
  if (data.waiver_priority != null) {
    card.appendChild(buildInfoLine(`Waiver priority: #${data.waiver_priority}`));
  }
  if (data.player_news.length > 0) {
    card.appendChild(buildPlayerNews(data.player_news));
  }
  return card;
}

function buildInfoLine(text) {
  const line = el("div", "in-season-info-line");
  line.textContent = text;
  return line;
}

// `players` is one entry per rostered player with a digest: {player_id,
// full_name, digest, items}. The digest (a Claude-generated summary of that
// player's last few days — see ffassistant.claude_news) is the main text;
// the underlying items are secondary, shown as a couple of clickable source
// links beneath rather than as the primary content.
function buildPlayerNews(players) {
  const wrap = el("div", "in-season-news");
  const heading = document.createElement("h4");
  heading.textContent = "Player News";
  wrap.appendChild(heading);

  const list = el("ul", "in-season-news-list");
  for (const player of players) {
    const li = document.createElement("li");
    li.className = "in-season-news-player";

    const nameSpan = document.createElement("span");
    nameSpan.className = "in-season-news-name";
    nameSpan.textContent = `${player.full_name}: `;
    li.appendChild(nameSpan);
    li.appendChild(document.createTextNode(player.digest));

    if (player.items.length > 0) {
      const sources = el("div", "in-season-news-sources");
      player.items.slice(0, 2).forEach((item, i) => {
        if (i > 0) sources.appendChild(document.createTextNode(" · "));
        const link = document.createElement("a");
        link.href = item.link;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = item.headline;
        sources.appendChild(link);
      });
      li.appendChild(sources);
    }

    list.appendChild(li);
  }
  wrap.appendChild(list);
  return wrap;
}

function buildColumnLabels() {
  const row = el("div", "in-season-column-labels");
  const rostered = document.createElement("h3");
  rostered.textContent = "Rostered";
  const available = document.createElement("h3");
  available.textContent = "Available";
  row.appendChild(rostered);
  row.appendChild(available);
  return row;
}

function buildPositionSection(position, group) {
  const section = el("div", "in-season-position");

  const heading = el("div", "in-season-position-heading");
  const chip = el("span", "position-chip");
  chip.textContent = position;
  chip.style.backgroundColor = positionColor(position);
  heading.appendChild(chip);
  section.appendChild(heading);

  const columns = el("div", "in-season-columns");
  columns.appendChild(buildColumn(group.rostered, "rostered"));
  columns.appendChild(buildColumn(group.available, "available"));
  section.appendChild(columns);

  return section;
}

function buildColumn(players, kind) {
  const col = el("div", "in-season-column");

  const list = el("ol", "in-season-player-list");
  if (players.length === 0) {
    const empty = document.createElement("li");
    empty.className = "in-season-empty";
    empty.textContent = "—";
    list.appendChild(empty);
  }

  for (const player of players) {
    const li = document.createElement("li");
    if (kind === "available" && player.beats_worst_rostered) li.classList.add("beats-worst");

    const rankSpan = document.createElement("span");
    rankSpan.className = "in-season-rank";
    rankSpan.textContent = player.rank != null ? `#${player.rank}` : "Unranked";
    li.appendChild(rankSpan);

    li.appendChild(document.createTextNode(" " + player.full_name));

    if (kind === "rostered" && player.status && player.status !== "healthy") {
      const badge = document.createElement("span");
      badge.className = "status-badge";
      badge.textContent = player.status;
      li.appendChild(badge);
    }
    list.appendChild(li);
  }
  col.appendChild(list);
  return col;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
