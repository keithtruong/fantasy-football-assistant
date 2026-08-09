import { api } from "./api.js";
import { positionColor } from "./positions.js";
import { renderScheduleTab } from "./schedule.js";

const WEEKLY_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];
const ROS_POSITIONS = ["QB", "RB", "WR", "TE"];

export async function renderInSeasonView(container, state) {
  const view = state.inSeasonTab; // "weekly" | "ros" | "schedule"

  if (view === "schedule") {
    await renderScheduleTab(container, state);
    return;
  }

  if (view === "weekly" && !state.week) {
    const prompt = document.createElement("p");
    prompt.className = "in-season-prompt";
    prompt.textContent = "Enter a week number above to see this week's rostered-vs-available breakdown.";
    container.appendChild(prompt);
    return;
  }

  const positions = view === "weekly" ? WEEKLY_POSITIONS : ROS_POSITIONS;
  const data = await api.getInSeason(state.leagueId, view, state.season, view === "weekly" ? state.week : null);

  const wrap = el("div", "in-season-view");
  for (const position of positions) {
    wrap.appendChild(buildPositionSection(position, data[position]));
  }
  container.appendChild(wrap);
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
  columns.appendChild(buildColumn("Rostered (worst first)", group.rostered, "rostered"));
  columns.appendChild(buildColumn("Available", group.available, "available"));
  section.appendChild(columns);

  return section;
}

function buildColumn(title, players, kind) {
  const col = el("div", "in-season-column");
  const heading = document.createElement("h4");
  heading.textContent = title;
  col.appendChild(heading);

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
