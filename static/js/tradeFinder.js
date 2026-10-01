import { api } from "./api.js";
import { positionColor } from "./positions.js";

const POSITIONS = ["QB", "RB", "WR", "TE"];

// Trade Finder: every team in the selected league, ranked against each other
// at each position by ROS rank — projected starters and bench depth separately
// (see ffassistant.trade_finder). A strength table up top for scanning, then
// one roster card per team below (same card pattern as the draft tool's
// Rosters tab). Teams are ordered mine first, then two-way fits, then
// one-way fits, then everyone else.
export async function renderTradeFinderTab(container, state) {
  const data = await api.getTradeFinder(state.leagueId, state.season);
  const teams = orderTeams(data.teams);

  const wrap = el("div", "trade-finder");
  wrap.appendChild(buildLegend(data));
  wrap.appendChild(buildStrengthTable(teams, data.teams.length));

  const cards = el("div", "rosters-scroll trade-finder-cards");
  for (const team of teams) cards.appendChild(buildTeamCard(team, data.teams.length));
  wrap.appendChild(cards);

  container.appendChild(wrap);
}

function fitScore(team) {
  if (team.is_mine) return 3;
  if (team.fits.two_way) return 2;
  return team.fits.they_can_offer.length || team.fits.they_need.length ? 1 : 0;
}

function orderTeams(teams) {
  return [...teams].sort((a, b) => fitScore(b) - fitScore(a) || a.team_name.localeCompare(b.team_name));
}

function buildLegend(data) {
  const p = el("p", "trade-finder-legend");
  const describe = (counts) => POSITIONS.map((pos) => `${counts[pos]} ${pos}`).join(", ");
  p.textContent =
    `Each position shows the team's league rank for projected starters (${describe(data.starter_counts)}) ` +
    `and for its next bench players (${describe(data.depth_counts)}), by ROS position rank — 1 is the ` +
    `strongest. "—" means nobody there is ranked. "Has" = their depth is top-half where your starters are ` +
    `bottom-half; "Needs" = their starters are bottom-half where your depth is top-half.`;
  return p;
}

// Green for the top third of the league, red for the bottom third, unshaded
// in between — just enough to scan the table; the numbers stay the point.
function strengthClass(rank, teamCount) {
  if (rank == null) return "tf-weak";
  if (rank <= teamCount / 3) return "tf-strong";
  if (rank > (teamCount * 2) / 3) return "tf-weak";
  return "";
}

function buildStrengthTable(teams, teamCount) {
  const scroll = el("div", "trade-finder-table-scroll");
  const table = el("table", "trade-finder-table");

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.appendChild(th("Team"));
  for (const pos of POSITIONS) {
    const cell = th("");
    const chip = el("span", "position-chip");
    chip.textContent = pos;
    chip.style.backgroundColor = positionColor(pos);
    cell.appendChild(chip);
    const sub = el("div", "tf-subhead");
    sub.textContent = "start · depth";
    cell.appendChild(sub);
    headRow.appendChild(cell);
  }
  headRow.appendChild(th("Trade fit"));
  head.appendChild(headRow);
  table.appendChild(head);

  const body = document.createElement("tbody");
  for (const team of teams) {
    const row = document.createElement("tr");
    if (team.is_mine) row.classList.add("tf-my-row");

    const nameCell = document.createElement("td");
    const nameLink = document.createElement("a");
    nameLink.href = `#tf-card-${team.team_id}`;
    nameLink.textContent = team.team_name;
    nameCell.appendChild(nameLink);
    const record = formatRecord(team.record);
    if (record) {
      const rec = el("span", "tf-record");
      rec.textContent = record;
      nameCell.appendChild(rec);
    }
    row.appendChild(nameCell);

    for (const pos of POSITIONS) {
      const tier = team.positions[pos];
      const cell = el("td", "tf-cell");
      const start = el("span", `tf-rank ${strengthClass(tier.starter_rank, teamCount)}`);
      start.textContent = rankText(tier.starter_rank);
      start.title = `Starters: avg ${pos}${tier.starter_avg ?? "—"}`;
      const depth = el("span", `tf-rank tf-depth ${strengthClass(tier.depth_rank, teamCount)}`);
      depth.textContent = rankText(tier.depth_rank);
      depth.title = `Depth: avg ${pos}${tier.depth_avg ?? "—"}`;
      cell.appendChild(start);
      cell.appendChild(depth);
      row.appendChild(cell);
    }

    row.appendChild(buildFitCell(team));
    body.appendChild(row);
  }
  table.appendChild(body);
  scroll.appendChild(table);
  return scroll;
}

function buildFitCell(team) {
  const cell = el("td", "tf-fit");
  if (team.is_mine) {
    cell.textContent = "You";
    return cell;
  }
  const { they_can_offer: offer, they_need: need, two_way: twoWay } = team.fits;
  if (twoWay) {
    const chip = el("span", "tf-two-way");
    chip.textContent = "Two-way";
    cell.appendChild(chip);
  }
  if (offer.length) cell.appendChild(fitLine(`Has: ${offer.join(", ")}`));
  if (need.length) cell.appendChild(fitLine(`Needs: ${need.join(", ")}`));
  if (!offer.length && !need.length) cell.appendChild(fitLine("—"));
  return cell;
}

function fitLine(text) {
  const line = el("div", "tf-fit-line");
  line.textContent = text;
  return line;
}

function buildTeamCard(team, teamCount) {
  const card = el("div", "team-card trade-finder-card");
  card.id = `tf-card-${team.team_id}`;
  if (team.is_mine) card.classList.add("my-team-card");

  const heading = document.createElement("h3");
  heading.textContent = team.team_name;
  card.appendChild(heading);

  for (const pos of POSITIONS) {
    const tier = team.positions[pos];
    const section = el("div", "team-card-position");

    const label = el("div", "team-card-position-label");
    const chip = el("span", "position-chip");
    chip.textContent = pos;
    chip.style.backgroundColor = positionColor(pos);
    label.appendChild(chip);
    const ranks = el("span", "position-relative-rank");
    ranks.textContent = `Start ${rankText(tier.starter_rank)} · Depth ${rankText(tier.depth_rank)} of ${teamCount}`;
    label.appendChild(ranks);
    section.appendChild(label);

    // Starters and the counted depth players at full strength, with a thin
    // divider between them; everyone past that dimmed, same as the Rosters tab.
    tier.starters.forEach((p) => section.appendChild(playerLine(p, "roster-player-starter")));
    tier.depth.forEach((p, i) =>
      section.appendChild(playerLine(p, "roster-player-starter" + (i === 0 ? " tf-depth-first" : "")))
    );
    tier.rest.forEach((p) => section.appendChild(playerLine(p, "roster-player-bench")));
    if (!tier.starters.length && !tier.depth.length && !tier.rest.length) {
      section.appendChild(playerLine(null, "roster-player-bench"));
    }

    card.appendChild(section);
  }
  return card;
}

function playerLine(player, className) {
  const line = el("div", `${className} tf-player`);
  if (!player) {
    line.textContent = "—";
    return line;
  }
  const rank = el("span", "tf-player-rank");
  rank.textContent = player.pos_rank != null ? `${player.position}${player.pos_rank}` : "NR";
  if (player.rank != null) rank.title = `ROS #${player.rank} overall`;
  line.appendChild(rank);
  line.appendChild(document.createTextNode(player.full_name));
  if (player.status && player.status !== "healthy") {
    const badge = el("span", "status-badge");
    badge.textContent = player.status;
    line.appendChild(badge);
  }
  return line;
}

function rankText(rank) {
  return rank == null ? "—" : `#${rank}`;
}

function formatRecord(record) {
  if (!record || record.wins == null) return "";
  return record.ties ? `${record.wins}-${record.losses}-${record.ties}` : `${record.wins}-${record.losses}`;
}

function th(text) {
  const cell = document.createElement("th");
  cell.textContent = text;
  return cell;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
