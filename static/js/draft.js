import { api } from "./api.js";
import { positionColor } from "./positions.js";
import { buildPlayerSearch } from "./playerSearch.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];

// Mirrors ffassistant/draft_logic.py's compute_pick_slot exactly — small enough
// that duplicating it client-side beats round-tripping to the server for it.
function computePickSlot(pickNumber, teamCount) {
  const roundNum = Math.floor((pickNumber - 1) / teamCount) + 1;
  const indexInRound = (pickNumber - 1) % teamCount;
  const draftPosition = roundNum % 2 === 1 ? indexInRound + 1 : teamCount - indexInRound;
  return { round: roundNum, draftPosition };
}

export async function renderDraftTab(container, state, refresh) {
  const [settings, teams, rankings, draftData] = await Promise.all([
    api.getSettings(state.leagueId),
    api.getTeams(state.leagueId),
    api.getRankings(state.leagueId, state.scoringFormat, state.season),
    api.getDraftPicks(state.leagueId, state.season),
  ]);

  const teamCount = teams.length;
  const myTeam = teams.find((t) => t.is_mine) || teams[0];
  const rankingsByPlayerId = new Map(rankings.map((r) => [r.player_id, r]));
  const draftedIds = new Set(draftData.picks.map((p) => p.player_id).filter(Boolean));
  const available = rankings.filter((r) => !draftedIds.has(r.player_id));

  const rosterSlotCounts = Object.fromEntries(
    settings.roster_slots.map((s) => [s.slot_name, s.slot_count])
  );

  container.appendChild(
    buildLayout({
      teams,
      myTeam,
      teamCount,
      available,
      rankingsByPlayerId,
      draftData,
      rosterSlotCounts,
      state,
      refresh,
    })
  );
}

function buildLayout(ctx) {
  const wrap = el("div", "draft-layout");
  wrap.appendChild(buildMain(ctx));
  wrap.appendChild(buildRail(ctx));
  return wrap;
}

// ---- Main column: pick entry + rank list ----

function buildMain(ctx) {
  const main = el("div", "draft-main");
  main.appendChild(buildPickEntry(ctx));
  main.appendChild(buildRankList(ctx));
  return main;
}

function buildPickEntry({ teams, draftData, state, refresh }) {
  const box = el("div", "pick-entry");
  const clock = draftData.on_the_clock;

  const clockLine = el("div", "on-the-clock");
  clockLine.textContent = `On the clock — Pick ${clock.pick_number} (Rd ${clock.round}): ${clock.team_name}`;
  box.appendChild(clockLine);

  const searchRow = buildPlayerSearch({
    leagueId: state.leagueId,
    season: state.season,
    placeholder: "Type a player name…",
    onSelect: async (player) => {
      await api.recordPick(state.leagueId, player.player_id, state.season);
      refresh();
    },
  });
  box.appendChild(searchRow);

  if (draftData.picks.length > 0) {
    const undoBtn = document.createElement("button");
    undoBtn.className = "undo-button";
    undoBtn.textContent = "Undo last pick";
    const lastPick = draftData.picks[draftData.picks.length - 1];
    undoBtn.addEventListener("click", async () => {
      await api.undoPick(state.leagueId, lastPick.draft_pick_id);
      refresh();
    });
    box.appendChild(undoBtn);
  }

  return box;
}

function buildRankList({ available, teamCount, draftData }) {
  const table = el("table", "rank-list");
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Rank</th><th>Player</th><th>Pos</th><th>Rd</th><th>SOS</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let lastTier = undefined;

  for (const player of available) {
    if (player.tier != null && player.tier !== lastTier) {
      const tierRow = document.createElement("tr");
      tierRow.className = "tier-divider";
      const td = document.createElement("td");
      td.colSpan = 5;
      td.textContent = `Tier ${player.tier}`;
      tierRow.appendChild(td);
      tbody.appendChild(tierRow);
      lastTier = player.tier;
    }

    const row = document.createElement("tr");

    const rankCell = document.createElement("td");
    rankCell.textContent = player.rank;
    row.appendChild(rankCell);

    const nameCell = document.createElement("td");
    nameCell.textContent = player.full_name;
    row.appendChild(nameCell);

    const posCell = document.createElement("td");
    const posChip = el("span", "position-chip");
    posChip.textContent = player.position || "?";
    posChip.style.backgroundColor = positionColor(player.position);
    posCell.appendChild(posChip);
    row.appendChild(posCell);

    const roundCell = document.createElement("td");
    const roundValue = Math.ceil(player.rank / teamCount);
    roundCell.textContent = `Rd ${roundValue}`;
    if (roundValue < draftData.on_the_clock.round) roundCell.className = "round-value-steal";
    row.appendChild(roundCell);

    const sosCell = document.createElement("td");
    sosCell.textContent = player.sos_rank != null ? `#${player.sos_rank}` : "";
    row.appendChild(sosCell);

    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

// ---- Rail: my roster, team-by-position matrix, ADP lookahead ----

function buildRail(ctx) {
  const rail = el("div", "draft-rail");
  rail.appendChild(buildCollapsible("My Roster", buildMyRoster(ctx)));
  rail.appendChild(buildCollapsible("Team Needs — safe to wait?", buildTeamMatrix(ctx)));
  rail.appendChild(buildCollapsible("ADP Lookahead", buildAdpLookahead(ctx)));
  return rail;
}

/** Team IDs that pick at least once before this team's next turn comes back around. */
function teamsBeforeMyNextPick(teams, myTeam, onTheClock, teamCount) {
  const upcoming = new Set();
  let pickNumber = onTheClock.pick_number;
  // Walk forward until we hit my own team's slot (cap at a full round as a safety bound).
  for (let i = 0; i < teamCount; i++) {
    const { draftPosition } = computePickSlot(pickNumber, teamCount);
    if (draftPosition === myTeam.draft_position) break;
    upcoming.add(draftPosition);
    pickNumber += 1;
  }
  return new Set(teams.filter((t) => upcoming.has(t.draft_position)).map((t) => t.team_id));
}

function buildCollapsible(title, contentEl) {
  const section = el("details", "rail-section");
  section.open = true;
  const summary = document.createElement("summary");
  summary.textContent = title;
  section.appendChild(summary);
  section.appendChild(contentEl);
  return section;
}

function buildMyRoster({ myTeam, rankingsByPlayerId }) {
  const list = el("div", "my-roster");
  for (const position of CORE_POSITIONS) {
    const players = myTeam.roster.filter((p) => p.position === position);
    if (players.length === 0) continue;
    const group = el("div", "roster-position-group");
    const label = el("span", "position-chip");
    label.textContent = position;
    label.style.backgroundColor = positionColor(position);
    group.appendChild(label);
    for (const player of players) {
      const ranking = rankingsByPlayerId.get(player.player_id);
      const byeText = ranking && ranking.bye_week ? ` (bye ${ranking.bye_week})` : "";
      const line = document.createElement("div");
      line.textContent = `${player.full_name}${byeText}`;
      group.appendChild(line);
    }
    list.appendChild(group);
  }
  return list;
}

function buildTeamMatrix({ teams, rosterSlotCounts, myTeam, teamCount, draftData }) {
  const table = el("table", "team-matrix");
  const caption = document.createElement("caption");
  caption.textContent = "Highlighted rows pick before your next turn";
  table.appendChild(caption);

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Team</th>" + CORE_POSITIONS.map((p) => `<th>${p}</th>`).join("");
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const upcomingTeamIds = teamsBeforeMyNextPick(teams, myTeam, draftData.on_the_clock, teamCount);

  const tbody = document.createElement("tbody");
  for (const team of teams) {
    const row = document.createElement("tr");
    if (team.is_mine) row.className = "my-team-row";
    else if (upcomingTeamIds.has(team.team_id)) row.className = "picks-before-mine";
    const nameCell = document.createElement("td");
    nameCell.textContent = team.team_name;
    row.appendChild(nameCell);

    for (const position of CORE_POSITIONS) {
      const count = team.roster.filter((p) => p.position === position).length;
      const required = rosterSlotCounts[position] || 0;
      const cell = document.createElement("td");
      cell.textContent = count;
      if (required > 0 && count >= required) cell.className = "slot-filled";
      row.appendChild(cell);
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

function buildAdpLookahead({ available }) {
  const list = el("ol", "adp-lookahead");
  const byAdp = available
    .filter((p) => p.adp != null)
    .sort((a, b) => a.adp - b.adp)
    .slice(0, 15);
  for (const player of byAdp) {
    const li = document.createElement("li");
    li.textContent = `${player.full_name} (${player.position}) — ADP ${player.adp.toFixed(1)}, your rank ${player.rank}`;
    list.appendChild(li);
  }
  return list;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
