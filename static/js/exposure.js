import { api } from "./api.js";
import { positionColor } from "./positions.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];
// Kickers/DST swing week to week on matchup script alone, not usage -- a "3+
// leagues" flag on them is just noise, so the heavy-rotation summary sticks
// to the positions where that many leagues actually means something.
const HIGH_EXPOSURE_POSITIONS = CORE_POSITIONS.filter((p) => p !== "DST" && p !== "K");
const HIGH_EXPOSURE_THRESHOLD = 3;

export async function renderExposureView(container) {
  const [data, starters] = await Promise.all([api.getExposure(), api.getStartersExposure()]);

  const wrap = el("div", "exposure-view");
  wrap.appendChild(buildWeeklyStarters(starters));
  wrap.appendChild(buildWeeklyTeamStarters(starters));
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
  section.appendChild(
    buildTeamChipList(zeroExposureTeams, "No Exposure — safe to ignore on Sundays", "You've got at least one player from every NFL team.")
  );
  return section;
}

// ---- Weekly Starters: my actual set lineup vs. my collective opponents' ----

function buildWeeklyStarters(starters) {
  const section = el("div", "exposure-section");
  const heading = document.createElement("h3");
  heading.textContent =
    starters.week != null ? `Weekly Starters (Week ${starters.week})` : "Weekly Starters";
  section.appendChild(heading);

  if (starters.week == null) {
    const note = document.createElement("p");
    note.className = "exposure-empty";
    note.textContent = "Couldn't figure out the current week yet — opponents' starters aren't available, but your own still are below.";
    section.appendChild(note);
  }

  section.appendChild(buildHighExposureSummary(starters.my_starters_by_position, starters.opponent_starters_by_position));

  const columns = el("div", "exposure-starters-columns");
  columns.appendChild(buildStartersColumn("My Starters", starters.my_starters_by_position));
  columns.appendChild(buildStartersColumn("Opponents' Starters", starters.opponent_starters_by_position));
  section.appendChild(columns);

  return section;
}

// ---- Weekly Starters by NFL team: both sides on one card (who to root for/
// against, at a glance), plus the same "quiet teams" chip list as before,
// now grouped with the team view it's actually about. ----

const VERDICT_LABELS = { root_for: "Root For", root_against: "Root Against", mixed: "Mixed" };
const VERDICT_TAG_CLASSES = { root_for: "tag-positive", root_against: "tag-negative", mixed: "tag-caution" };

function buildWeeklyTeamStarters(starters) {
  const section = el("div", "exposure-section");
  const heading = document.createElement("h3");
  heading.textContent = "This Week by NFL Team";
  section.appendChild(heading);

  const teams = starters.starters_by_nfl_team || [];
  section.appendChild(buildTeamVerdictSummary(teams, starters.quiet_nfl_teams));

  if (teams.length === 0) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "—";
    section.appendChild(empty);
  } else {
    const grid = el("div", "exposure-nfl-grid");
    for (const team of teams) {
      grid.appendChild(buildWeeklyTeamCard(team));
    }
    section.appendChild(grid);
  }

  return section;
}

// Quick-scan version of the card grid below: just the team codes, grouped by
// verdict (mixed teams are left out here -- neither a clean root-for nor
// root-against, and no different from the full grid where they're already
// clearly tagged).
function buildTeamVerdictSummary(teams, quietTeams) {
  const wrap = el("div", "exposure-team-summary");
  const rootFor = teams.filter((t) => t.verdict === "root_for").map((t) => t.nfl_team);
  const rootAgainst = teams.filter((t) => t.verdict === "root_against").map((t) => t.nfl_team);

  wrap.appendChild(buildTeamChipList(rootFor, "Root For", "No clean root-for teams this week."));
  wrap.appendChild(buildTeamChipList(rootAgainst, "Root Against", "No clean root-against teams this week."));
  wrap.appendChild(
    buildTeamChipList(
      quietTeams,
      "Not Moving the Needle",
      "Every NFL team has at least one starter in play for you or an opponent this week."
    )
  );
  return wrap;
}

function buildWeeklyTeamCard(team) {
  const card = el("div", "exposure-nfl-card");

  const header = el("div", "exposure-nfl-card-header");
  const name = document.createElement("h4");
  name.textContent = team.nfl_team;
  header.appendChild(name);
  const verdict = el("span", `tag-chip ${VERDICT_TAG_CLASSES[team.verdict]}`);
  verdict.textContent = VERDICT_LABELS[team.verdict];
  header.appendChild(verdict);
  card.appendChild(header);

  const sides = el("div", "exposure-weekly-team-sides");
  sides.appendChild(buildWeeklyTeamSide("Mine", team.my_players));
  sides.appendChild(buildWeeklyTeamSide("Opponents'", team.opponent_players));
  card.appendChild(sides);

  return card;
}

function buildWeeklyTeamSide(label, players) {
  const side = el("div", "exposure-weekly-team-side");
  const labelSpan = el("span", "exposure-weekly-team-side-label");
  labelSpan.textContent = label;
  side.appendChild(labelSpan);

  if (players.length === 0) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "—";
    side.appendChild(empty);
  } else {
    side.appendChild(buildPlayerList(players));
  }
  return side;
}

// Non-K/DST starters (QB/RB/WR/TE) in play for HIGH_EXPOSURE_THRESHOLD+ of
// either "my" or "opponents'" leagues this week -- the players whose actual
// game result swings the most matchups at once, surfaced before the full
// position breakdown rather than buried in it.
function buildHighExposureSummary(myByPosition, opponentByPosition) {
  const wrap = el("div", "exposure-highlight-summary");
  wrap.appendChild(buildHighExposureRow("Mine", myByPosition));
  wrap.appendChild(buildHighExposureRow("Opponents'", opponentByPosition));
  return wrap;
}

function buildHighExposureRow(label, playersByPosition) {
  const row = el("div", "exposure-highlight-row");
  const labelSpan = el("span", "exposure-highlight-label");
  labelSpan.textContent = `${label} (${HIGH_EXPOSURE_THRESHOLD}+ leagues):`;
  row.appendChild(labelSpan);

  const players = HIGH_EXPOSURE_POSITIONS.flatMap((position) => playersByPosition[position] || [])
    .filter((p) => p.league_count >= HIGH_EXPOSURE_THRESHOLD)
    .sort((a, b) => b.league_count - a.league_count || a.full_name.localeCompare(b.full_name));

  if (players.length === 0) {
    const none = el("span", "exposure-highlight-none");
    none.textContent = "None this week";
    row.appendChild(none);
    return row;
  }

  const chips = el("span", "exposure-highlight-chips");
  for (const player of players) {
    const chip = el("span", "exposure-highlight-chip");
    chip.textContent = `${player.full_name} (${player.position}) x${player.league_count}`;
    chips.appendChild(chip);
  }
  row.appendChild(chips);
  return row;
}

function buildStartersColumn(title, playersByPosition) {
  const column = el("div", "exposure-starters-column");
  const heading = document.createElement("h4");
  heading.textContent = title;
  column.appendChild(heading);

  let anyPlayers = false;
  for (const position of CORE_POSITIONS) {
    const players = playersByPosition[position] || [];
    if (players.length === 0) continue;
    anyPlayers = true;
    column.appendChild(buildPositionGroup(position, players));
  }

  if (!anyPlayers) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = "—";
    column.appendChild(empty);
  }

  return column;
}

function buildTeamChipList(teams, title, emptyMessage) {
  const wrap = el("div", "exposure-zero-wrap");
  const heading = document.createElement("h4");
  heading.textContent = title;
  wrap.appendChild(heading);

  if (!teams || teams.length === 0) {
    const empty = document.createElement("p");
    empty.className = "exposure-empty";
    empty.textContent = emptyMessage;
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

  card.appendChild(buildPlayerList(team.players));

  return card;
}

function buildPlayerList(players) {
  const list = el("ul", "exposure-nfl-players");
  for (const player of players) {
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
  return list;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
