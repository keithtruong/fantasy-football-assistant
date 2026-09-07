import { api } from "./api.js";

const PLATFORMS = ["sleeper", "espn", "yahoo"];

// Standard-ish default so a manual league doesn't start with an empty rail —
// still fully editable afterward in the "Scoring & roster slots" section.
const DEFAULT_MANUAL_ROSTER_SLOTS = [
  { slot_name: "QB", slot_count: 1 },
  { slot_name: "RB", slot_count: 2 },
  { slot_name: "WR", slot_count: 2 },
  { slot_name: "TE", slot_count: 1 },
  { slot_name: "FLEX", slot_count: 1 },
  { slot_name: "DST", slot_count: 1 },
  { slot_name: "K", slot_count: 1 },
  { slot_name: "BENCH", slot_count: 6 },
];

export async function renderLeagueSettings(container, refreshLeagues) {
  const leagues = await api.getLeagues(true);

  const wrap = document.createElement("div");
  wrap.className = "league-settings";

  wrap.appendChild(await buildSeasonPanel());
  wrap.appendChild(buildAddLeagueForm(refreshLeagues));
  for (const league of leagues) {
    wrap.appendChild(buildLeagueCard(league, refreshLeagues));
  }

  container.appendChild(wrap);
}

async function buildSeasonPanel() {
  const card = document.createElement("div");
  card.className = "settings-card";

  const heading = document.createElement("h3");
  heading.textContent = "Season";
  card.appendChild(heading);

  const help = document.createElement("p");
  help.className = "form-help";
  help.textContent =
    "The in-season section figures out the current week automatically (a live NFL-week lookup — " +
    "no setup needed). This date is only a manual fallback for if that lookup is ever unreachable: " +
    "the Tuesday week 1 begins, matching the weekly waiver-prep cadence.";
  card.appendChild(help);

  const season = new Date().getFullYear();
  const current = await api.getSeason(season);

  const form = document.createElement("form");
  form.className = "add-league-form";
  form.innerHTML = `
    <input type="number" name="season" value="${season}" disabled />
    <input type="date" name="week1_start_date" value="${current.week1_start_date || ""}" required />
    <button type="submit">Save</button>
  `;

  const status = document.createElement("div");
  status.className = "form-status";
  status.textContent =
    current.current_week != null
      ? `Current week: ${current.current_week}`
      : "Outside weeks 1-17 (offseason)";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const week1StartDate = form.elements.week1_start_date.value;
    try {
      const result = await api.setSeasonWeek1(season, week1StartDate);
      status.textContent = result.current_week != null
        ? `Saved — current week: ${result.current_week}`
        : "Saved — outside weeks 1-17 (offseason)";
      status.className = "form-status";
    } catch (err) {
      status.textContent = `Failed: ${err.message}`;
      status.className = "form-status form-status-error";
    }
  });

  card.appendChild(form);
  card.appendChild(status);
  return card;
}

function buildAddLeagueForm(refreshLeagues) {
  const card = document.createElement("div");
  card.className = "settings-card";

  const heading = document.createElement("h3");
  heading.textContent = "Add a league";
  card.appendChild(heading);

  const form = document.createElement("form");
  form.className = "add-league-form";

  form.innerHTML = `
    <input type="text" name="name" placeholder="League name (just a label — anything's fine)" required />
    <select name="platform">
      ${PLATFORMS.map((p) => `<option value="${p}">${p}</option>`).join("")}
      <option value="manual">manual (no platform yet — placeholder)</option>
    </select>
    <input type="text" name="platform_league_id" placeholder="League ID from the platform's URL" required />
    <input type="number" name="season" placeholder="Season" value="${new Date().getFullYear()}" />
    <button type="submit">Add &amp; Sync</button>
  `;

  const platformSelect = form.elements.platform;
  const leagueIdInput = form.elements.platform_league_id;
  const seasonInput = form.elements.season;
  const submitButton = form.querySelector("button[type=submit]");

  const help = document.createElement("p");
  help.className = "form-help";
  const platformHelp =
    "Not the league name — the ID from the URL: " +
    "Sleeper looks like <code>1257056342493908992</code>, " +
    "ESPN like <code>360508</code> (the <code>leagueId=</code> param), " +
    "Yahoo like <code>461.l.656302</code>.";
  const manualHelp =
    "No platform connector yet — you'll add teams and roster slots by hand below once it's created. " +
    "Only Draft/Grid/Draft + Grid/Tiers/Rosters work for a manual league; Post-Draft, Exposure, " +
    "In-season, and W-L don't apply to it.";
  help.innerHTML = platformHelp;
  form.appendChild(help);

  function applyPlatformMode() {
    const isManual = platformSelect.value === "manual";
    leagueIdInput.required = !isManual;
    leagueIdInput.style.display = isManual ? "none" : "";
    seasonInput.style.display = isManual ? "none" : "";
    submitButton.textContent = isManual ? "Add league" : "Add & Sync";
    help.innerHTML = isManual ? manualHelp : platformHelp;
  }
  platformSelect.addEventListener("change", applyPlatformMode);
  applyPlatformMode();

  const status = document.createElement("div");
  status.className = "form-status";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const isManual = platformSelect.value === "manual";
    const data = Object.fromEntries(new FormData(form));
    status.textContent = isManual ? "Adding…" : "Syncing…";
    status.className = "form-status";
    try {
      const result = await api.createLeague(data);
      if (isManual) {
        // Seed a standard roster-slot default so Draft/Grid work immediately —
        // fully editable afterward in the league card below.
        await api.setRosterSlots(result.league_id, DEFAULT_MANUAL_ROSTER_SLOTS);
      }
      form.reset();
      applyPlatformMode();
      await refreshLeagues();
      highlightNewLeague(result.league_id);
      showToast(
        isManual
          ? "Manual league added — add teams and set your draft order below."
          : result.already_existed
            ? "Already existed — re-synced it."
            : "League added and synced."
      );
    } catch (err) {
      status.textContent = `Failed: ${err.message}`;
      status.className = "form-status form-status-error";
    }
  });

  card.appendChild(form);
  card.appendChild(status);
  return card;
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add("toast-visible"), 10);
  setTimeout(() => {
    toast.classList.remove("toast-visible");
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function highlightNewLeague(leagueId) {
  const card = document.querySelector(`.settings-card[data-league-id="${leagueId}"]`);
  if (!card) return;
  card.classList.add("just-added");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => card.classList.remove("just-added"), 2000);
}

function buildLeagueCard(league, refreshLeagues) {
  const card = document.createElement("div");
  card.className = "settings-card";
  card.dataset.leagueId = league.league_id;
  if (!league.active) card.classList.add("league-inactive");

  const header = document.createElement("div");
  header.className = "league-card-header";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.value = league.name;
  nameInput.className = "league-name-input";
  nameInput.addEventListener("change", async () => {
    await api.updateLeague(league.league_id, { name: nameInput.value });
    await refreshLeagues();
  });
  header.appendChild(nameInput);

  const isManual = league.platform === "manual";

  const meta = document.createElement("span");
  meta.className = "league-meta";
  const platformLabel = isManual ? "manual (placeholder)" : league.platform;
  meta.textContent = `${platformLabel} · ${league.team_count} teams${league.my_team_name ? ` · you: ${league.my_team_name}` : ""}`;
  header.appendChild(meta);

  const activeLabel = document.createElement("label");
  activeLabel.className = "league-active-toggle";
  const activeCheckbox = document.createElement("input");
  activeCheckbox.type = "checkbox";
  activeCheckbox.checked = !!league.active;
  activeCheckbox.addEventListener("change", async () => {
    await api.updateLeague(league.league_id, { active: activeCheckbox.checked });
    await refreshLeagues();
  });
  activeLabel.appendChild(activeCheckbox);
  activeLabel.appendChild(document.createTextNode(" active"));
  header.appendChild(activeLabel);

  if (isManual) {
    const manualNote = document.createElement("span");
    manualNote.className = "league-meta";
    manualNote.textContent = "no platform to sync — edit teams/roster slots below";
    header.appendChild(manualNote);
  } else {
    const resyncBtn = document.createElement("button");
    resyncBtn.type = "button";
    resyncBtn.textContent = "Re-sync";
    resyncBtn.addEventListener("click", async () => {
      resyncBtn.disabled = true;
      resyncBtn.textContent = "Syncing…";
      try {
        await api.resyncLeague(league.league_id, new Date().getFullYear());
      } finally {
        resyncBtn.disabled = false;
        resyncBtn.textContent = "Re-sync";
        await refreshLeagues();
      }
    });
    header.appendChild(resyncBtn);
  }

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "delete-league-button";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", async () => {
    const confirmed = confirm(
      `Delete "${league.name}"? This removes all its teams, draft picks, and settings. This can't be undone.`
    );
    if (!confirmed) return;
    await api.deleteLeague(league.league_id);
    await refreshLeagues();
  });
  header.appendChild(deleteBtn);

  card.appendChild(header);

  const teamsSection = document.createElement("details");
  teamsSection.className = "teams-section";
  const summary = document.createElement("summary");
  summary.textContent = "Draft order & your team";
  teamsSection.appendChild(summary);

  const reloadTeamsSection = async () => {
    teamsSection.querySelectorAll(":scope > :not(summary)").forEach((el) => el.remove());
    const teams = await api.getTeams(league.league_id);
    // Patch the header's team count in place rather than going through the
    // full refreshLeagues() page rebuild, which would re-collapse this
    // <details> right after adding each team — annoying when adding several
    // in a row before a draft.
    if (isManual) {
      meta.textContent = `manual (placeholder) · ${teams.length} teams${league.my_team_name ? ` · you: ${league.my_team_name}` : ""}`;
      teamsSection.appendChild(buildAddTeamForm(league, reloadTeamsSection));
    }
    teamsSection.appendChild(buildTeamsTable(league, teams, isManual, reloadTeamsSection));
  };

  let teamsLoaded = false;
  teamsSection.addEventListener("toggle", async () => {
    if (teamsSection.open && !teamsLoaded) {
      teamsLoaded = true;
      await reloadTeamsSection();
    }
  });

  card.appendChild(teamsSection);

  const settingsSection = document.createElement("details");
  settingsSection.className = "teams-section";
  const settingsSummary = document.createElement("summary");
  settingsSummary.textContent = "Scoring & roster slots";
  settingsSection.appendChild(settingsSummary);

  const reloadSettingsSection = async () => {
    settingsSection.querySelectorAll(":scope > :not(summary)").forEach((el) => el.remove());
    const settings = await api.getSettings(league.league_id);
    settingsSection.appendChild(
      isManual ? buildManualRosterSlotsEditor(league, settings, reloadSettingsSection) : buildSettingsView(settings)
    );
  };

  let settingsLoaded = false;
  settingsSection.addEventListener("toggle", async () => {
    if (settingsSection.open && !settingsLoaded) {
      settingsLoaded = true;
      await reloadSettingsSection();
    }
  });

  card.appendChild(settingsSection);
  return card;
}

/** Manual-league-only: a name input + button above the teams table for adding
 * one team at a time — the hand-entered stand-in for what a platform sync
 * would otherwise populate. */
function buildAddTeamForm(league, onAdded) {
  const form = document.createElement("form");
  form.className = "add-league-form add-team-form";
  form.innerHTML = `
    <input type="text" name="team_name" placeholder="Team name" required />
    <button type="submit">Add team</button>
  `;
  const status = document.createElement("span");
  status.className = "form-status";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const teamName = form.elements.team_name.value.trim();
    if (!teamName) return;
    try {
      await api.addManualTeam(league.league_id, teamName);
      form.reset();
      status.textContent = "";
      await onAdded();
    } catch (err) {
      status.textContent = err.message;
      status.className = "form-status form-status-error";
    }
  });

  const wrap = document.createElement("div");
  wrap.appendChild(form);
  wrap.appendChild(status);
  return wrap;
}

function buildSettingsView(settings) {
  const wrap = document.createElement("div");
  wrap.className = "settings-view";

  const slotsHeading = document.createElement("h4");
  slotsHeading.textContent = "Roster slots";
  wrap.appendChild(slotsHeading);

  const slotsList = document.createElement("div");
  slotsList.className = "slots-list";
  for (const slot of settings.roster_slots) {
    const chip = document.createElement("span");
    chip.className = "slot-chip";
    chip.textContent = `${slot.slot_name} ×${slot.slot_count}`;
    slotsList.appendChild(chip);
  }
  wrap.appendChild(slotsList);

  const scoringHeading = document.createElement("h4");
  scoringHeading.textContent = `Scoring (${settings.scoring.length} rules)`;
  wrap.appendChild(scoringHeading);

  const scoringTable = document.createElement("table");
  scoringTable.className = "scoring-table";
  const tbody = document.createElement("tbody");
  const sorted = [...settings.scoring].sort((a, b) => a.stat_key.localeCompare(b.stat_key));
  for (const rule of sorted) {
    const row = document.createElement("tr");
    row.innerHTML = `<td>${rule.stat_key}</td><td>${rule.points}</td>`;
    tbody.appendChild(row);
  }
  scoringTable.appendChild(tbody);

  const scoringScroll = document.createElement("div");
  scoringScroll.className = "scoring-scroll";
  scoringScroll.appendChild(scoringTable);
  wrap.appendChild(scoringScroll);

  return wrap;
}

const MANUAL_SLOT_NAME_OPTIONS = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "DST", "K", "BENCH", "IR"];

/** Manual-league-only: an editable roster-slot table (name + count per row,
 * add/remove rows, one Save button that full-replaces roster_slots) standing
 * in for what a platform sync would otherwise populate — this is what the
 * Grid tab's round count and the Draft rail's position-fill signal read. */
function buildManualRosterSlotsEditor(league, settings, onChanged) {
  const wrap = document.createElement("div");
  wrap.className = "settings-view";

  const slotsHeading = document.createElement("h4");
  slotsHeading.textContent = "Roster slots";
  wrap.appendChild(slotsHeading);

  const help = document.createElement("p");
  help.className = "form-help";
  help.textContent =
    "Rounds in the Grid tab = the sum of these counts. No scoring rules for manual leagues — " +
    "Draft/Grid/Tiers/Rosters don't need them, just pick a scoring format from the dropdown above.";
  wrap.appendChild(help);

  const rowsWrap = document.createElement("div");
  rowsWrap.className = "roster-slot-rows";
  wrap.appendChild(rowsWrap);

  function addSlotRow(slotName, slotCount) {
    const row = document.createElement("div");
    row.className = "roster-slot-row";

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = slotName ?? "";
    nameInput.placeholder = "Slot (e.g. QB, FLEX, BENCH)";
    nameInput.setAttribute("list", "manual-slot-name-options");
    nameInput.className = "roster-slot-name-input";
    row.appendChild(nameInput);

    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "0";
    countInput.value = slotCount ?? "";
    countInput.className = "roster-slot-count-input";
    row.appendChild(countInput);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "×";
    removeBtn.className = "roster-slot-remove-button";
    removeBtn.addEventListener("click", () => row.remove());
    row.appendChild(removeBtn);

    rowsWrap.appendChild(row);
  }

  const existing = [...settings.roster_slots].sort((a, b) => a.slot_name.localeCompare(b.slot_name));
  for (const slot of existing) addSlotRow(slot.slot_name, slot.slot_count);
  if (existing.length === 0) addSlotRow("", "");

  // Shared browser datalist so slot-name inputs get autocomplete without a
  // hardcoded <select>, since a league might legitimately use a slot name
  // outside the common list.
  const datalist = document.createElement("datalist");
  datalist.id = "manual-slot-name-options";
  datalist.innerHTML = MANUAL_SLOT_NAME_OPTIONS.map((n) => `<option value="${n}">`).join("");
  wrap.appendChild(datalist);

  const buttonRow = document.createElement("div");
  buttonRow.className = "roster-slot-button-row";

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.textContent = "Add slot";
  addBtn.addEventListener("click", () => addSlotRow("", ""));
  buttonRow.appendChild(addBtn);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.textContent = "Save roster slots";
  buttonRow.appendChild(saveBtn);

  const status = document.createElement("span");
  status.className = "form-status";
  buttonRow.appendChild(status);

  saveBtn.addEventListener("click", async () => {
    const slots = [...rowsWrap.querySelectorAll(".roster-slot-row")]
      .map((row) => ({
        slot_name: row.querySelector(".roster-slot-name-input").value.trim(),
        slot_count: Number(row.querySelector(".roster-slot-count-input").value),
      }))
      .filter((s) => s.slot_name);

    if (slots.length === 0) {
      status.textContent = "Add at least one slot.";
      status.className = "form-status form-status-error";
      return;
    }

    saveBtn.disabled = true;
    status.textContent = "Saving…";
    status.className = "form-status";
    try {
      await api.setRosterSlots(league.league_id, slots);
      await onChanged();
    } catch (err) {
      status.textContent = err.message;
      status.className = "form-status form-status-error";
      saveBtn.disabled = false;
    }
  });

  wrap.appendChild(buttonRow);
  return wrap;
}

function buildTeamsTable(league, teams, isManual, onChanged) {
  const table = document.createElement("table");
  table.className = "teams-table";
  const nameHeader = isManual ? "Team Name" : "Pulled Name";
  table.innerHTML = `<thead><tr><th>Draft #</th><th>${nameHeader}</th><th>Display Name</th><th>Mine?</th>${isManual ? "<th></th>" : ""}</tr></thead>`;

  const tbody = document.createElement("tbody");
  const sorted = [...teams].sort((a, b) => (a.draft_position || 0) - (b.draft_position || 0));

  for (const team of sorted) {
    const row = document.createElement("tr");

    const posCell = document.createElement("td");
    const posInput = document.createElement("input");
    posInput.type = "number";
    posInput.min = "1";
    posInput.value = team.draft_position ?? "";
    posInput.className = "draft-position-input";
    posInput.addEventListener("change", async () => {
      await api.updateTeam(league.league_id, team.team_id, { draft_position: Number(posInput.value) });
    });
    posCell.appendChild(posInput);
    row.appendChild(posCell);

    const nameCell = document.createElement("td");
    nameCell.textContent = team.platform_team_name;
    row.appendChild(nameCell);

    const displayNameCell = document.createElement("td");
    const displayNameInput = document.createElement("input");
    displayNameInput.type = "text";
    displayNameInput.value = team.display_name ?? "";
    displayNameInput.placeholder = team.platform_team_name;
    displayNameInput.className = "display-name-input";
    displayNameInput.title = "Overrides the pulled name everywhere in this tool — leave blank to use the pulled name.";
    displayNameInput.addEventListener("change", async () => {
      await api.updateTeam(league.league_id, team.team_id, { display_name: displayNameInput.value });
    });
    displayNameCell.appendChild(displayNameInput);
    row.appendChild(displayNameCell);

    const mineCell = document.createElement("td");
    const mineRadio = document.createElement("input");
    mineRadio.type = "radio";
    mineRadio.name = `is-mine-${league.league_id}`;
    mineRadio.checked = !!team.is_mine;
    mineRadio.addEventListener("change", async () => {
      await api.updateTeam(league.league_id, team.team_id, { is_mine: true });
    });
    mineCell.appendChild(mineRadio);
    row.appendChild(mineCell);

    if (isManual) {
      const deleteCell = document.createElement("td");
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "delete-team-button";
      deleteBtn.textContent = "Remove";
      deleteBtn.addEventListener("click", async () => {
        const confirmed = confirm(`Remove "${team.platform_team_name}" from this league?`);
        if (!confirmed) return;
        try {
          await api.deleteManualTeam(league.league_id, team.team_id);
          await onChanged();
        } catch (err) {
          alert(err.message);
        }
      });
      deleteCell.appendChild(deleteBtn);
      row.appendChild(deleteCell);
    }

    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}
