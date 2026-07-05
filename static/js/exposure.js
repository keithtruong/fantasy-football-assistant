import { api } from "./api.js";
import { positionColor } from "./positions.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];

export async function renderExposureView(container) {
  const data = await api.getExposure();

  const wrap = el("div", "exposure-view");
  wrap.appendChild(buildPlayerExposure(data.players_by_position, data.active_league_count));
  wrap.appendChild(buildNflTeamExposure(data.nfl_teams, data.zero_exposure_teams));
  container.appendChild(wrap);
}

function buildPlayerExposure(playersByPosition, activeLeagueCount) {
  const section = el("div", "exposure-section");
  const heading = document.createElement("h3");
  heading.textContent = `Player Exposure (across ${activeLeagueCount} active leagues)`;
  section.appendChild(heading);

  let anyPlayers = false;
  for (const position of CORE_POSITIONS) {
    const players = playersByPosition[position] || [];
    if (players.length === 0) continue;
    anyPlayers = true;
    section.appendChild(buildPositionGroup(position, players));
  }

  if (!anyPlayers) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "No rostered players found yet — sync a league or mark a team as yours in League Settings.";
    section.appendChild(empty);
  }

  return section;
}

function buildPositionGroup(position, players) {
  const group = el("div", "exposure-position-group");
  const label = el("span", "position-chip");
  label.textContent = position;
  label.style.backgroundColor = positionColor(position);
  group.appendChild(label);

  const table = el("table", "exposure-table borderless-table");
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Player</th><th>Leagues</th><th>Where</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const player of players) {
    const row = document.createElement("tr");

    const nameCell = document.createElement("td");
    nameCell.textContent = player.full_name;

    const countCell = document.createElement("td");
    countCell.textContent = player.league_count;

    const leaguesCell = document.createElement("td");
    leaguesCell.className = "exposure-leagues-cell";
    leaguesCell.textContent = player.leagues.join(", ");

    row.append(nameCell, countCell, leaguesCell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  group.appendChild(table);
  return group;
}

function buildNflTeamExposure(nflTeams, zeroExposureTeams) {
  const section = el("div", "exposure-section");
  const heading = document.createElement("h3");
  heading.textContent = "NFL Team Exposure";
  section.appendChild(heading);

  if (nflTeams.length === 0) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "—";
    section.appendChild(empty);
    return section;
  }

  const grid = el("div", "exposure-nfl-grid");
  for (const team of nflTeams) {
    grid.appendChild(buildNflTeamCard(team));
  }
  section.appendChild(grid);
  section.appendChild(buildZeroExposureList(zeroExposureTeams));
  return section;
}

function buildZeroExposureList(teams) {
  const wrap = el("div", "exposure-zero-wrap");
  const heading = document.createElement("h4");
  heading.textContent = "No Exposure — safe to ignore on Sundays";
  wrap.appendChild(heading);

  if (!teams || teams.length === 0) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "You've got at least one player from every NFL team.";
    wrap.appendChild(empty);
    return wrap;
  }

  const chips = el("div", "exposure-zero-chips");
  for (const team of teams) {
    const chip = el("span", "exposure-zero-chip");
    chip.textContent = team;
    chips.appendChild(chip);
  }
  wrap.appendChild(chips);
  return wrap;
}

function buildNflTeamCard(team) {
  const card = el("div", "exposure-nfl-card");

  const header = el("div", "exposure-nfl-card-header");
  const name = document.createElement("h4");
  name.textContent = team.nfl_team;
  header.appendChild(name);
  if (team.bye_week != null) {
    const bye = el("span", "exposure-bye-chip");
    bye.textContent = `Bye ${team.bye_week}`;
    header.appendChild(bye);
  }
  card.appendChild(header);

  const summary = el("div", "exposure-nfl-summary");
  const spotWord = team.roster_spot_count === 1 ? "roster spot" : "roster spots";
  const playerWord = team.unique_player_count === 1 ? "player" : "players";
  summary.textContent = `${team.roster_spot_count} ${spotWord} · ${team.unique_player_count} ${playerWord}`;
  card.appendChild(summary);

  const list = el("ul", "exposure-nfl-players");
  for (const player of team.players) {
    const li = document.createElement("li");
    const nameSpan = document.createElement("span");
    nameSpan.textContent = `${player.full_name} (${player.position})`;
    li.appendChild(nameSpan);
    if (player.league_count >= 2) {
      const badge = el("span", "exposure-player-league-count");
      badge.textContent = `x${player.league_count}`;
      li.appendChild(badge);
    }
    list.appendChild(li);
  }
  card.appendChild(list);

  return card;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
