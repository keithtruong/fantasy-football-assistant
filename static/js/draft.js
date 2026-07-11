import { api } from "./api.js";
import { positionColor } from "./positions.js";
import { buildPlayerSearch } from "./playerSearch.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"];

// Notable-gap thresholds for the rank-list Tags column. Tuned to flag real
// signal, not every minor disagreement between sources.
const REACH_WAIT_ADP_GAP = 12; // rank this many spots off ADP (~a round) -> "Wait"/"Reach"
const SOS_NOTABLE_RANK = 8; // top/bottom 8 of 32 teams -> "Hard SOS" / "Easy SOS"
const BYE_RISK_STACK_COUNT = 2; // 2+ same-position rostered players sharing a bye

function nextManualTag(current) {
  if (current === "sleeper") return "shy_away";
  if (current === "shy_away") return null;
  return "sleeper";
}

// Mirrors ffassistant/draft_logic.py's compute_pick_slot exactly — small enough
// that duplicating it client-side beats round-tripping to the server for it.
function computePickSlot(pickNumber, teamCount) {
  const roundNum = Math.floor((pickNumber - 1) / teamCount) + 1;
  const indexInRound = (pickNumber - 1) % teamCount;
  const draftPosition = roundNum % 2 === 1 ? indexInRound + 1 : teamCount - indexInRound;
  return { round: roundNum, draftPosition };
}

export async function renderDraftTab(container, state, refresh) {
  const [settings, teams, rankings, draftData, exposure] = await Promise.all([
    api.getSettings(state.leagueId),
    api.getTeams(state.leagueId),
    api.getRankings(state.leagueId, state.scoringFormat, state.season),
    api.getDraftPicks(state.leagueId, state.season),
    api.getExposure(),
  ]);

  const teamCount = teams.length;
  const myTeam = teams.find((t) => t.is_mine) || teams[0];
  const rankingsByPlayerId = new Map(rankings.map((r) => [r.player_id, r]));
  const draftedIds = new Set(draftData.picks.map((p) => p.player_id).filter(Boolean));
  const available = rankings.filter((r) => !draftedIds.has(r.player_id));

  const rosterSlotCounts = Object.fromEntries(
    settings.roster_slots.map((s) => [s.slot_name, s.slot_count])
  );

  // Cross-league exposure — a tiebreaker signal, not a rank-derived one, so it's
  // flattened from the position-grouped /api/exposure response into a plain lookup.
  const exposureByPlayerId = new Map();
  for (const players of Object.values(exposure.players_by_position)) {
    for (const player of players) {
      exposureByPlayerId.set(player.player_id, player);
    }
  }

  container.appendChild(
    buildLayout({
      teams,
      myTeam,
      teamCount,
      available,
      rankingsByPlayerId,
      exposureByPlayerId,
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

function buildPickEntry({ teams, draftData, available, state, refresh }) {
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

  box.appendChild(buildQuickPicks(available, state, refresh));

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

/** One-click drafting of the top 5 available (by rank) — saves the search-type-click
 * round trip when the pick is obvious. */
function buildQuickPicks(available, state, refresh) {
  const wrap = el("div", "quick-picks");

  const label = document.createElement("span");
  label.className = "quick-picks-label";
  label.textContent = "Quick pick:";
  wrap.appendChild(label);

  for (const player of available.slice(0, 5)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "quick-pick-button";
    btn.textContent = `${player.full_name} (${player.position || "?"})`;
    btn.addEventListener("click", async () => {
      await api.recordPick(state.leagueId, player.player_id, state.season);
      refresh();
    });
    wrap.appendChild(btn);
  }

  return wrap;
}

/** Reach/Wait, Sleeper/Shy-away, Hard/Easy SOS, Bye Risk, exposure — computed
 * per row, shown as compact tag chips rather than dedicated always-on columns,
 * since most players won't trip most of these. */
function computeTags(player, { myTeam, rankingsByPlayerId, exposureByPlayerId }) {
  const tags = [];

  if (player.rank != null && player.adp != null) {
    const gap = player.adp - player.rank; // positive -> market has them later than we do
    if (gap >= REACH_WAIT_ADP_GAP) tags.push({ label: "Wait", kind: "positive" });
    else if (gap <= -REACH_WAIT_ADP_GAP) tags.push({ label: "Reach", kind: "caution" });
  }

  // Manual, not computed: Keith's own target/avoid call on this player,
  // independent of rank (e.g. injury/contract/scheme concerns rank can't see).
  if (player.manual_tag === "sleeper") tags.push({ label: "Sleeper", kind: "positive" });
  else if (player.manual_tag === "shy_away") tags.push({ label: "Shy-away", kind: "caution" });

  if (player.sos_rank != null) {
    if (player.sos_rank <= SOS_NOTABLE_RANK) tags.push({ label: "Hard SOS", kind: "caution" });
    else if (player.sos_rank > 32 - SOS_NOTABLE_RANK) tags.push({ label: "Easy SOS", kind: "positive" });
  }

  if (player.bye_week != null && myTeam) {
    const samePositionByeMatches = myTeam.roster
      .filter((p) => p.position === player.position)
      .map((p) => rankingsByPlayerId.get(p.player_id)?.bye_week)
      .filter((bye) => bye === player.bye_week).length;
    if (samePositionByeMatches >= BYE_RISK_STACK_COUNT) tags.push({ label: "Bye Risk", kind: "caution" });
  }

  // Cross-league exposure — neither good nor bad on its own (a stud owned
  // elsewhere is still a stud), just a fact to weigh as a tiebreaker.
  const exposure = exposureByPlayerId.get(player.player_id);
  if (exposure) {
    const label = `${exposure.league_count} League${exposure.league_count === 1 ? "" : "s"}`;
    tags.push({ label, kind: "neutral" });
  }

  return tags;
}

/** If the draft proceeded exactly in rank order from here on, which currently-available
 * players would land in one of my future picks — the "worst case" player per round, since
 * any real-world deviation from rank order can only let a better player fall, not worse. */
function computeFuturePickIds({ available, teamCount, myTeam, rosterSlotCounts, draftData }) {
  const totalRounds = Object.values(rosterSlotCounts).reduce((sum, n) => sum + n, 0);
  const totalPicks = teamCount * totalRounds;
  const futurePicks = new Map(); // player_id -> round

  let pickNumber = draftData.on_the_clock.pick_number;
  let i = 0;
  while (pickNumber <= totalPicks && i < available.length) {
    const { round, draftPosition } = computePickSlot(pickNumber, teamCount);
    if (draftPosition === myTeam.draft_position) {
      futurePicks.set(available[i].player_id, round);
    }
    pickNumber += 1;
    i += 1;
  }
  return futurePicks;
}

function buildRankList({
  available,
  teamCount,
  myTeam,
  rankingsByPlayerId,
  exposureByPlayerId,
  rosterSlotCounts,
  draftData,
  refresh,
}) {
  const table = el("table", "rank-list");
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Rank</th><th>Player Name</th><th>Position</th><th>Tier</th><th>Team</th><th>ADP</th><th>Tags</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  const futurePicks = computeFuturePickIds({ available, teamCount, myTeam, rosterSlotCounts, draftData });

  for (const player of available) {
    const row = document.createElement("tr");
    // Round-breakpoint line: rank-based (not position-in-list), matching the
    // legacy spreadsheet's conditional formatting — e.g. a 12-team league gets
    // a line under rank 12, 24, 36... regardless of who's already been drafted.
    if (player.rank != null && player.rank % teamCount === 0) {
      row.classList.add("round-break");
    }
    if (futurePicks.has(player.player_id)) {
      row.classList.add("future-pick-row");
      row.title = `Your worst-case pick in Round ${futurePicks.get(player.player_id)} if the draft goes exactly by rank from here`;
    }

    const rankCell = document.createElement("td");
    rankCell.textContent = player.rank;
    row.appendChild(rankCell);

    const nameCell = document.createElement("td");
    nameCell.textContent = player.full_name;
    nameCell.className = "player-name-cell";
    nameCell.title = "Click to cycle your target/avoid call: none → Sleeper → Shy-away";
    nameCell.addEventListener("click", async () => {
      await api.setManualTag(player.player_id, nextManualTag(player.manual_tag));
      refresh();
    });
    row.appendChild(nameCell);

    const posCell = document.createElement("td");
    const posChip = el("span", "position-chip");
    posChip.textContent = player.position || "?";
    posChip.style.backgroundColor = positionColor(player.position);
    posCell.appendChild(posChip);
    row.appendChild(posCell);

    const tierCell = document.createElement("td");
    tierCell.textContent = player.tier != null ? player.tier : "—";
    row.appendChild(tierCell);

    const teamCell = document.createElement("td");
    teamCell.textContent = player.nfl_team || "—";
    row.appendChild(teamCell);

    const adpCell = document.createElement("td");
    adpCell.textContent = player.adp != null ? player.adp.toFixed(1) : "—";
    row.appendChild(adpCell);

    const tagsCell = document.createElement("td");
    const tagsInner = el("div", "tags-cell-inner");
    for (const tag of computeTags(player, { myTeam, rankingsByPlayerId, exposureByPlayerId })) {
      const chip = document.createElement("span");
      chip.className = `tag-chip tag-${tag.kind}`;
      chip.textContent = tag.label;
      tagsInner.appendChild(chip);
    }
    tagsCell.appendChild(tagsInner);
    row.appendChild(tagsCell);

    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

// ---- Rail: my roster, positions filled, ADP lookahead ----

function buildRail(ctx) {
  const rail = el("div", "draft-rail");
  rail.appendChild(buildCollapsible("My Roster", buildMyRoster(ctx)));
  rail.appendChild(buildCollapsible("Positions Filled", buildTeamMatrix(ctx)));
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

function buildMyRoster({ myTeam, rankingsByPlayerId, rosterSlotCounts }) {
  const wrap = el("div", "my-roster");
  for (const position of CORE_POSITIONS) {
    const players = myTeam.roster
      .filter((p) => p.position === position)
      .sort((a, b) => (a.pick_number || 0) - (b.pick_number || 0));
    const starterCount = rosterSlotCounts[position] || 0;
    if (starterCount === 0 && players.length === 0) continue;

    const group = el("div", "roster-position-group");
    const label = el("span", "position-chip");
    label.textContent = position;
    label.style.backgroundColor = positionColor(position);
    group.appendChild(label);

    const table = el("table", "roster-slot-table borderless-table");
    const tbody = document.createElement("tbody");
    for (let i = 0; i < starterCount; i++) {
      tbody.appendChild(buildRosterSlotRow(players[i], rankingsByPlayerId, false));
    }
    for (let i = starterCount; i < players.length; i++) {
      tbody.appendChild(buildRosterSlotRow(players[i], rankingsByPlayerId, true));
    }
    table.appendChild(tbody);
    group.appendChild(table);
    wrap.appendChild(group);
  }
  return wrap;
}

function buildRosterSlotRow(player, rankingsByPlayerId, isBench) {
  const row = document.createElement("tr");
  row.className = isBench ? "roster-player-bench" : "roster-player-starter";

  const nameCell = document.createElement("td");
  const byeCell = document.createElement("td");
  byeCell.className = "roster-bye-col";

  if (!player) {
    nameCell.textContent = "—";
    row.classList.add("roster-slot-empty");
  } else {
    nameCell.textContent = player.full_name;
    const bye = rankingsByPlayerId.get(player.player_id)?.bye_week;
    byeCell.textContent = bye != null ? bye : "";
  }
  row.appendChild(nameCell);
  row.appendChild(byeCell);
  return row;
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
  const table = el("table", "adp-lookahead-table borderless-table");
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Player</th><th>Pos</th><th>ADP</th><th>Your Rank</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  const byAdp = available
    .filter((p) => p.adp != null)
    .sort((a, b) => a.adp - b.adp)
    .slice(0, 15);

  for (const player of byAdp) {
    const row = document.createElement("tr");
    // Same signal as the rank list's Wait/Reach tags: your rank much better
    // than ADP -> market may let them slip past ADP, safe-to-wait evidence.
    // Your rank much worse than ADP -> don't count on them lasting.
    if (player.rank != null) {
      const gap = player.adp - player.rank;
      if (gap >= REACH_WAIT_ADP_GAP) row.classList.add("adp-gap-positive");
      else if (gap <= -REACH_WAIT_ADP_GAP) row.classList.add("adp-gap-caution");
    }

    const nameCell = document.createElement("td");
    nameCell.textContent = player.full_name;
    const posCell = document.createElement("td");
    posCell.textContent = player.position;
    const adpCell = document.createElement("td");
    adpCell.textContent = player.adp.toFixed(1);
    const rankCell = document.createElement("td");
    rankCell.textContent = player.rank;
    row.append(nameCell, posCell, adpCell, rankCell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
