import { api } from "./api.js";
import { positionColor } from "./positions.js";

// Matches the rankings provider's tier coverage (see ffassistant/connectors/rankings.py) —
// no tier pages are published for DST/K, so those positions have no tier data to show.
const TIER_POSITIONS = ["QB", "RB", "WR", "TE"];
const TIERS_SHOWN = 3;

export async function renderTiersTab(container, state) {
  const [rankings, draftData] = await Promise.all([
    api.getRankings(state.leagueId, state.scoringFormat, state.season),
    api.getDraftPicks(state.leagueId, state.season),
  ]);

  const draftedIds = new Set(draftData.picks.map((p) => p.player_id).filter(Boolean));

  const board = document.createElement("div");
  board.className = "tiers-board";
  for (const position of TIER_POSITIONS) {
    board.appendChild(buildPositionColumn(position, rankings, draftedIds));
  }
  container.appendChild(board);
}

function buildPositionColumn(position, rankings, draftedIds) {
  const players = rankings
    .filter((r) => r.position === position && r.tier != null)
    .sort((a, b) => a.rank - b.rank);

  const tierNumbers = [...new Set(players.map((p) => p.tier))].sort((a, b) => a - b);
  // "Current" tier = the lowest-numbered tier that still has an available player —
  // a tier fully drafted is one you've already passed on, not one to plan around.
  const currentIndex = tierNumbers.findIndex((tier) =>
    players.some((p) => p.tier === tier && !draftedIds.has(p.player_id))
  );
  const shownTiers = currentIndex === -1 ? [] : tierNumbers.slice(currentIndex, currentIndex + TIERS_SHOWN);

  const column = document.createElement("div");
  column.className = "tier-column";

  const heading = document.createElement("div");
  heading.className = "tier-column-heading";
  const chip = document.createElement("span");
  chip.className = "position-chip";
  chip.textContent = position;
  chip.style.backgroundColor = positionColor(position);
  heading.appendChild(chip);
  column.appendChild(heading);

  if (shownTiers.length === 0) {
    const empty = document.createElement("p");
    empty.className = "tier-column-empty";
    empty.textContent = tierNumbers.length === 0 ? "No tier data." : "All tiers drafted.";
    column.appendChild(empty);
    return column;
  }

  shownTiers.forEach((tierNum, i) => {
    const tierPlayers = players.filter((p) => p.tier === tierNum);
    column.appendChild(buildTierBlock(tierNum, tierPlayers, draftedIds, i === 0));
  });

  return column;
}

function buildTierBlock(tierNum, players, draftedIds, isCurrent) {
  const block = document.createElement("div");
  block.className = "tier-block" + (isCurrent ? " tier-block-current" : "");

  const label = document.createElement("div");
  label.className = "tier-block-label";
  label.textContent = `Tier ${tierNum}`;
  block.appendChild(label);

  const table = document.createElement("table");
  table.className = "tier-player-table borderless-table";
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Rank</th><th>Player</th><th>Team</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const player of players) {
    const row = document.createElement("tr");
    if (draftedIds.has(player.player_id)) row.className = "tier-player-drafted";

    const rankCell = document.createElement("td");
    rankCell.textContent = player.rank;
    const nameCell = document.createElement("td");
    nameCell.textContent = player.full_name;
    const teamCell = document.createElement("td");
    teamCell.textContent = player.nfl_team || "—";
    row.append(rankCell, nameCell, teamCell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  block.appendChild(table);

  return block;
}
