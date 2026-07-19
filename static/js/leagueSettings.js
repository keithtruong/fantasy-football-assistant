import { api } from "./api.js";

const PLATFORMS = ["sleeper", "espn", "yahoo"];

export async function renderLeagueSettings(container, refreshLeagues) {
  const leagues = await api.getLeagues(true);

  const wrap = document.createElement("div");
  wrap.className = "league-settings";

  wrap.appendChild(buildAddLeagueForm(refreshLeagues));
  for (const league of leagues) {
    wrap.appendChild(buildLeagueCard(league, refreshLeagues));
  }

  container.appendChild(wrap);
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
    </select>
    <input type="text" name="platform_league_id" placeholder="League ID from the platform's URL" required />
    <input type="number" name="season" placeholder="Season" value="${new Date().getFullYear()}" />
    <button type="submit">Add &amp; Sync</button>
  `;

  const help = document.createElement("p");
  help.className = "form-help";
  help.innerHTML =
    "Not the league name — the ID from the URL: " +
    "Sleeper looks like <code>1257056342493908992</code>, " +
    "ESPN like <code>360508</code> (the <code>leagueId=</code> param), " +
    "Yahoo like <code>461.l.656302</code>.";
  form.appendChild(help);

  const status = document.createElement("div");
  status.className = "form-status";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    status.textContent = "Syncing…";
    try {
      const result = await api.createLeague(data);
      form.reset();
      await refreshLeagues();
      highlightNewLeague(result.league_id);
      showToast(result.already_existed ? "Already existed — re-synced it." : "League added and synced.");
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

  const meta = document.createElement("span");
  meta.className = "league-meta";
  meta.textContent = `${league.platform} · ${league.team_count} teams${league.my_team_name ? ` · you: ${league.my_team_name}` : ""}`;
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

  let loaded = false;
  teamsSection.addEventListener("toggle", async () => {
    if (teamsSection.open && !loaded) {
      loaded = true;
      const teams = await api.getTeams(league.league_id);
      teamsSection.appendChild(buildTeamsTable(league, teams));
    }
  });

  card.appendChild(teamsSection);

  const settingsSection = document.createElement("details");
  settingsSection.className = "teams-section";
  const settingsSummary = document.createElement("summary");
  settingsSummary.textContent = "Scoring & roster slots";
  settingsSection.appendChild(settingsSummary);

  let settingsLoaded = false;
  settingsSection.addEventListener("toggle", async () => {
    if (settingsSection.open && !settingsLoaded) {
      settingsLoaded = true;
      const settings = await api.getSettings(league.league_id);
      settingsSection.appendChild(buildSettingsView(settings));
    }
  });

  card.appendChild(settingsSection);
  return card;
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

function buildTeamsTable(league, teams) {
  const table = document.createElement("table");
  table.className = "teams-table";
  table.innerHTML =
    "<thead><tr><th>Draft #</th><th>Pulled Name</th><th>Display Name</th><th>Mine?</th></tr></thead>";

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

    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}
