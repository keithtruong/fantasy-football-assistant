import { api } from "./api.js";
import { positionColor } from "./positions.js";
import { buildPlayerSearch } from "./playerSearch.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];

export async function renderGridTab(container, state, refresh) {
  const [settings, teams, draftData] = await Promise.all([
    api.getSettings(state.leagueId),
    api.getTeams(state.leagueId),
    api.getDraftPicks(state.leagueId, state.season),
  ]);

  const teamsByDraftPosition = [...teams].sort((a, b) => (a.draft_position || 0) - (b.draft_position || 0));
  const totalRounds = settings.roster_slots.reduce((sum, s) => sum + s.slot_count, 0) || 1;

  const pickByRoundAndTeam = new Map();
  for (const pick of draftData.picks) {
    pickByRoundAndTeam.set(`${pick.round}:${pick.team_id}`, pick);
  }

  const rosterSlotCounts = Object.fromEntries(
    settings.roster_slots.map((s) => [s.slot_name, s.slot_count])
  );

  container.appendChild(buildToolbar(draftData.picks.length, state, refresh));
  container.appendChild(buildBoard(teamsByDraftPosition, totalRounds, pickByRoundAndTeam, state, refresh));
  container.appendChild(buildPositionSummary(teamsByDraftPosition, rosterSlotCounts));
}

function buildToolbar(pickCount, state, refresh) {
  const bar = document.createElement("div");
  bar.className = "grid-toolbar";

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "clear-all-button";
  clearBtn.textContent = "Clear all picks";
  clearBtn.disabled = pickCount === 0;
  clearBtn.addEventListener("click", async () => {
    const confirmed = window.confirm(
      `Clear all ${pickCount} pick${pickCount === 1 ? "" : "s"} for this league/season? This can't be undone.`
    );
    if (!confirmed) return;
    await api.clearPicks(state.leagueId, state.season);
    refresh();
  });
  bar.appendChild(clearBtn);

  return bar;
}

function buildBoard(teams, totalRounds, pickByRoundAndTeam, state, refresh) {
  const scrollWrap = document.createElement("div");
  scrollWrap.className = "grid-scroll";

  const table = document.createElement("table");
  table.className = "draft-grid";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Rd</th>" + teams.map((t) => `<th>${t.team_name}</th>`).join("");
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let round = 1; round <= totalRounds; round++) {
    const row = document.createElement("tr");
    const roundCell = document.createElement("td");
    roundCell.textContent = round;
    roundCell.className = "grid-round-label";
    row.appendChild(roundCell);

    for (const team of teams) {
      const pick = pickByRoundAndTeam.get(`${round}:${team.team_id}`);
      row.appendChild(buildCell(pick, state, refresh));
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);

  scrollWrap.appendChild(table);
  return scrollWrap;
}

function buildCell(pick, state, refresh) {
  const cell = document.createElement("td");
  if (!pick || !pick.player_id) {
    cell.className = "grid-cell-empty";
    return cell;
  }

  cell.className = "grid-cell-filled";
  renderCellContent(cell, pick);

  cell.addEventListener("click", () => {
    if (cell.querySelector(".search-row")) return; // already editing
    cell.innerHTML = "";
    const search = buildPlayerSearch({
      leagueId: state.leagueId,
      season: state.season,
      placeholder: "Replace with…",
      onSelect: async (player) => {
        await api.editPick(state.leagueId, pick.draft_pick_id, player.player_id);
        refresh();
      },
    });
    cell.appendChild(search);
    search.querySelector("input").focus();
  });

  return cell;
}

function renderCellContent(cell, pick) {
  cell.innerHTML = "";
  const chip = document.createElement("span");
  chip.className = "position-chip grid-position-chip";
  chip.textContent = pick.position || "?";
  chip.style.backgroundColor = positionColor(pick.position);
  cell.appendChild(chip);
  cell.appendChild(document.createTextNode(" " + pick.full_name));
}

function buildPositionSummary(teams, rosterSlotCounts) {
  const wrap = document.createElement("div");
  wrap.className = "position-summary-wrap";

  const heading = document.createElement("h3");
  heading.textContent = "Position counts";
  wrap.appendChild(heading);

  const scrollWrap = document.createElement("div");
  scrollWrap.className = "grid-scroll";

  const table = document.createElement("table");
  table.className = "position-summary";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Pos</th>" + teams.map((t) => `<th>${t.team_name}</th>`).join("");
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const position of CORE_POSITIONS) {
    const row = document.createElement("tr");
    const posCell = document.createElement("td");
    posCell.textContent = position;
    row.appendChild(posCell);

    const required = rosterSlotCounts[position] || 0;
    for (const team of teams) {
      const count = team.roster.filter((p) => p.position === position).length;
      const cell = document.createElement("td");
      cell.textContent = count;
      if (count === 0) cell.classList.add("count-zero");
      else if (required > 0 && count >= required) cell.classList.add("slot-filled");
      row.appendChild(cell);
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);

  scrollWrap.appendChild(table);
  wrap.appendChild(scrollWrap);
  return wrap;
}
