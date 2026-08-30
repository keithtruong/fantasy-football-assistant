import { api } from "./api.js";
import { positionColor } from "./positions.js";

export async function renderPostDraftTab(container, state, refresh) {
  const postDraft = await api.getPostDraft(state.leagueId, state.season);

  container.appendChild(buildToolbar(postDraft, state, refresh));

  if (!postDraft.completed) {
    const hint = el("p", "post-draft-hint");
    hint.textContent =
      "Mark this league's draft complete to freeze the current rankings as the " +
      "comparison point for every pick — future rankings refreshes won't move it.";
    container.appendChild(hint);
    return;
  }

  const [teams, settings] = await Promise.all([
    api.getTeams(state.leagueId),
    api.getSettings(state.leagueId),
  ]);
  const totalRounds = settings.roster_slots.reduce((sum, s) => sum + s.slot_count, 0) || 1;

  container.appendChild(buildBoard(postDraft, teams, totalRounds, state));
}

function buildToolbar(postDraft, state, refresh) {
  const bar = el("div", "post-draft-toolbar");

  if (postDraft.completed) {
    const status = el("span", "post-draft-status");
    status.textContent = `Draft marked complete (${postDraft.scoring_format}), ${formatTimestamp(postDraft.completed_at)}`;
    bar.appendChild(status);

    const reopenBtn = document.createElement("button");
    reopenBtn.type = "button";
    reopenBtn.className = "undo-button";
    reopenBtn.textContent = "Reopen draft";
    reopenBtn.title = "Clears the completion flag and the frozen rankings snapshot";
    reopenBtn.addEventListener("click", async () => {
      const confirmed = window.confirm(
        "Reopen this draft? This clears the frozen rankings snapshot — picks and notes are kept."
      );
      if (!confirmed) return;
      await api.reopenDraft(state.leagueId, state.season);
      refresh();
    });
    bar.appendChild(reopenBtn);
  } else {
    const completeBtn = document.createElement("button");
    completeBtn.type = "button";
    completeBtn.className = "quick-pick-button";
    completeBtn.textContent = "Mark draft complete";
    completeBtn.addEventListener("click", async () => {
      const confirmed = window.confirm(
        `Mark this draft complete using ${state.scoringFormat} rankings as the snapshot?`
      );
      if (!confirmed) return;
      try {
        await api.completeDraft(state.leagueId, state.season, state.scoringFormat);
        refresh();
      } catch (err) {
        window.alert(err.message);
      }
    });
    bar.appendChild(completeBtn);
  }

  return bar;
}

/** Team x round grid — same shape as the Grid tab's draft board, so every
 * team's round N sits in the same table row (identical height) and every
 * team's column is the same fixed width, rather than independent per-team
 * cards whose heights/columns drifted with how many picks each team had. */
function buildBoard(postDraft, teams, totalRounds, state) {
  const teamsByDraftPosition = [...teams].sort(
    (a, b) => (a.draft_position || 0) - (b.draft_position || 0)
  );

  const pickByRoundAndTeam = new Map();
  for (const pick of postDraft.picks) {
    pickByRoundAndTeam.set(`${pick.round}:${pick.team_id}`, pick);
  }
  const summaryByTeam = computeTeamSummaries(postDraft.picks);

  const scrollWrap = el("div", "grid-scroll");
  const table = el("table", "post-draft-grid");

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.appendChild(document.createElement("th"));
  for (const team of teamsByDraftPosition) {
    headerRow.appendChild(buildTeamHeader(team, summaryByTeam.get(team.team_id)));
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let round = 1; round <= totalRounds; round++) {
    const row = document.createElement("tr");
    const roundCell = document.createElement("td");
    roundCell.textContent = round;
    roundCell.className = "grid-round-label";
    row.appendChild(roundCell);

    for (const team of teamsByDraftPosition) {
      row.appendChild(buildPickCell(pickByRoundAndTeam.get(`${round}:${team.team_id}`), state));
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);

  scrollWrap.appendChild(table);
  return scrollWrap;
}

/** Net value = sum of pick-vs-rank diffs across the team's whole draft — the
 * single number that answers "did this manager do well overall". */
function computeTeamSummaries(picks) {
  const byTeam = new Map();
  for (const pick of picks) {
    if (!byTeam.has(pick.team_id)) byTeam.set(pick.team_id, []);
    byTeam.get(pick.team_id).push(pick);
  }

  const summaries = new Map();
  for (const [teamId, teamPicks] of byTeam) {
    const withRank = teamPicks.filter((p) => p.rank_diff != null);
    const netValue = withRank.reduce((sum, p) => sum + p.rank_diff, 0);
    const valueCount = teamPicks.filter((p) => p.notable && p.rank_diff > 0).length;
    const reachCount = teamPicks.filter((p) => p.notable && p.rank_diff < 0).length;
    summaries.set(teamId, { netValue, valueCount, reachCount });
  }
  return summaries;
}

function buildTeamHeader(team, summary) {
  const th = document.createElement("th");
  th.className = "post-draft-team-header";
  if (team.is_mine) th.classList.add("my-team-col");

  const name = el("div", "post-draft-team-name");
  name.textContent = team.team_name;
  th.appendChild(name);

  if (summary) {
    const netChip = el("span", "tag-chip");
    netChip.classList.add(summary.netValue >= 0 ? "tag-positive" : "tag-negative");
    netChip.textContent = `Net ${summary.netValue > 0 ? "+" : ""}${summary.netValue}`;
    netChip.title = "Sum of pick-vs-snapshot-rank differences across this team's draft — higher is better";
    th.appendChild(netChip);

    const breakdown = el("div", "post-draft-team-breakdown");
    breakdown.textContent = `${summary.valueCount} value, ${summary.reachCount} reach`;
    th.appendChild(breakdown);
  }

  return th;
}

function buildPickCell(pick, state) {
  const cell = document.createElement("td");
  cell.className = "post-draft-cell";
  if (!pick || !pick.player_id) {
    cell.classList.add("grid-cell-empty");
    return cell;
  }
  // Reach (taken ahead of rank — no value) is the bad outcome, so it gets the
  // red indicator; a value pick (fell past its rank) gets green.
  if (pick.notable) {
    cell.classList.add(pick.rank_diff > 0 ? "post-draft-cell-value" : "post-draft-cell-reach");
  }

  const playerLine = el("div", "post-draft-cell-player");
  const posChip = el("span", "position-chip grid-position-chip");
  posChip.textContent = pick.position || "?";
  posChip.style.backgroundColor = positionColor(pick.position);
  playerLine.appendChild(posChip);
  playerLine.appendChild(document.createTextNode(pick.full_name));
  cell.appendChild(playerLine);

  const metaLine = el("div", "post-draft-cell-meta");
  const pickText = document.createElement("span");
  pickText.className = "post-draft-cell-pick";
  pickText.textContent = `Pick ${pick.pick_number}`;
  metaLine.appendChild(pickText);

  if (pick.rank_diff != null) {
    const chip = el("span", "tag-chip");
    // Only color notable picks (the backend's +/-5 threshold) green/red — small
    // diffs inside that band are noise, not a real reach or value, so they stay
    // neutral gray to keep the real outliers visually distinct.
    if (pick.notable) {
      chip.classList.add(pick.rank_diff > 0 ? "tag-positive" : "tag-negative");
    } else {
      chip.classList.add("tag-neutral");
    }
    const sign = pick.rank_diff > 0 ? "+" : "";
    chip.textContent = `Rk ${pick.snapshot_rank} (${sign}${pick.rank_diff})`;
    chip.title = pick.notable
      ? pick.rank_diff > 0
        ? "Fell past their snapshot rank — value"
        : "Taken ahead of their snapshot rank — reach"
      : "Close to their snapshot rank — no real reach or value";
    metaLine.appendChild(chip);
  }
  cell.appendChild(metaLine);

  const notesInput = document.createElement("input");
  notesInput.type = "text";
  notesInput.className = "post-draft-notes-input";
  notesInput.placeholder = "Note…";
  notesInput.value = pick.notes || "";
  notesInput.addEventListener("change", async () => {
    await api.updatePickNotes(state.leagueId, pick.draft_pick_id, notesInput.value);
  });
  cell.appendChild(notesInput);

  return cell;
}

function formatTimestamp(sqliteDatetime) {
  if (!sqliteDatetime) return "";
  const date = new Date(sqliteDatetime.replace(" ", "T") + "Z");
  return date.toLocaleString();
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
