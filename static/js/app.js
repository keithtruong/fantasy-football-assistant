import { api } from "./api.js";
import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";
import { renderTiersTab } from "./tiers.js";
import { renderRostersTab } from "./rosters.js";
import { renderLeagueSettings } from "./leagueSettings.js";
import { renderInSeasonView } from "./inSeason.js";
import { renderExposureView } from "./exposure.js";
import { renderWlView } from "./wl.js";

const state = {
  leagueId: null,
  season: new Date().getFullYear(),
  scoringFormat: "full_ppr",
  activeSection: "draft_tool",
  activeTab: "draft",
  inSeasonTab: "weekly",
  week: null,
  wlTab: "games",
  wlYear: new Date().getFullYear(),
};

const tabRenderers = {
  draft: renderDraftTab,
  grid: renderGridTab,
  tiers: renderTiersTab,
  rosters: renderRostersTab,
};

const tabContent = document.getElementById("tab-content");
const leagueSelectRow = document.getElementById("league-select-row");
const draftToolControls = document.getElementById("draft-tool-controls");
const tabBar = document.getElementById("tab-bar");
const inSeasonControls = document.getElementById("in-season-controls");
const inSeasonTabBar = document.getElementById("in-season-tab-bar");
const wlControls = document.getElementById("wl-controls");
const wlTabBar = document.getElementById("wl-tab-bar");
const leagueSelect = document.getElementById("league-select");
const weekInput = document.getElementById("in-season-week-input");
const wlYearInput = document.getElementById("wl-year-input");
const refreshRankingsButton = document.getElementById("refresh-rankings-button");
const rankingsSyncStatus = document.getElementById("rankings-sync-status");

const SECTION_ROWS = {
  draft_tool: [leagueSelectRow, draftToolControls, tabBar],
  in_season: [leagueSelectRow, inSeasonControls, inSeasonTabBar],
  exposure: [],
  league_settings: [],
  wl: [wlControls, wlTabBar],
};

function setVisibleRows(visibleRows) {
  const all = [leagueSelectRow, draftToolControls, tabBar, inSeasonControls, inSeasonTabBar, wlControls, wlTabBar];
  for (const row of all) {
    row.style.display = visibleRows.includes(row) ? "" : "none";
  }
}

async function renderActive() {
  tabContent.innerHTML = "";
  setVisibleRows(SECTION_ROWS[state.activeSection]);

  try {
    if (state.activeSection === "league_settings") {
      await renderLeagueSettings(tabContent, reloadLeagues);
      return;
    }

    if (state.activeSection === "exposure") {
      await renderExposureView(tabContent);
      return;
    }

    if (state.activeSection === "wl") {
      await renderWlView(tabContent, state);
      return;
    }

    if (!state.leagueId) return;

    if (state.activeSection === "in_season") {
      await renderInSeasonView(tabContent, state, renderActive);
      return;
    }

    await tabRenderers[state.activeTab](tabContent, state, renderActive);
  } catch (err) {
    // Any failed fetch (e.g. no team marked as yours yet) otherwise left the
    // page silently blank — tabContent was already cleared above, and nothing
    // catching the rejection meant no message ever reached the user.
    tabContent.innerHTML = "";
    const errorMsg = document.createElement("p");
    errorMsg.className = "app-error";
    errorMsg.textContent = err.message;
    tabContent.appendChild(errorMsg);
  }
}

async function reloadLeagues() {
  const leagues = await api.getLeagues();
  const previousSelection = state.leagueId;
  leagueSelect.innerHTML = leagues.map((l) => `<option value="${l.league_id}">${l.name}</option>`).join("");

  const stillExists = leagues.some((l) => l.league_id === previousSelection);
  state.leagueId = stillExists ? previousSelection : leagues[0]?.league_id ?? null;
  if (state.leagueId != null) leagueSelect.value = state.leagueId;

  // Re-render whichever section is actually showing — adding a league while ON
  // League Settings must reflect in the list without needing a full page reload.
  await renderActive();
}

function formatSyncedAt(sqliteDatetime) {
  if (!sqliteDatetime) return "Never synced";
  // SQLite's datetime('now') is UTC with a space separator — make it an
  // unambiguous ISO string before handing it to Date.
  const date = new Date(sqliteDatetime.replace(" ", "T") + "Z");
  return `Last synced ${date.toLocaleString()}`;
}

async function refreshSyncStatus() {
  try {
    const status = await api.getRankingsSyncStatus(state.season, state.scoringFormat);
    rankingsSyncStatus.textContent = formatSyncedAt(status.synced_at);
    rankingsSyncStatus.className = "rankings-sync-status";
  } catch {
    // Non-critical — leave whatever status text was already showing.
  }
}

function wireTabGroup(selector, dataAttr, stateKey) {
  document.querySelectorAll(selector).forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(selector).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state[stateKey] = btn.dataset[dataAttr];
      renderActive();
    });
  });
}

function init() {
  document.querySelectorAll(".section-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".section-button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeSection = btn.dataset.section;
      renderActive();
    });
  });

  leagueSelect.addEventListener("change", () => {
    state.leagueId = Number(leagueSelect.value);
    renderActive();
  });

  const scoringSelect = document.getElementById("scoring-format-select");
  scoringSelect.value = state.scoringFormat;
  scoringSelect.addEventListener("change", () => {
    state.scoringFormat = scoringSelect.value;
    renderActive();
    refreshSyncStatus();
  });

  refreshRankingsButton.addEventListener("click", async () => {
    refreshRankingsButton.disabled = true;
    rankingsSyncStatus.textContent = "Refreshing…";
    rankingsSyncStatus.className = "rankings-sync-status";
    try {
      const result = await api.syncRankings(state.season, state.scoringFormat);
      const unresolvedNote = result.unresolved_count ? `, ${result.unresolved_count} unresolved` : "";
      rankingsSyncStatus.textContent =
        `${formatSyncedAt(result.synced_at)} — ${result.player_count} players, ${result.tier_count} tiers${unresolvedNote}`;
      rankingsSyncStatus.className = result.unresolved_count
        ? "rankings-sync-status rankings-sync-warning"
        : "rankings-sync-status";
      await renderActive();
    } catch (err) {
      rankingsSyncStatus.textContent = err.message;
      rankingsSyncStatus.className = "rankings-sync-status rankings-sync-error";
    } finally {
      refreshRankingsButton.disabled = false;
    }
  });
  refreshSyncStatus();

  wireTabGroup("#tab-bar .tab-button", "tab", "activeTab");
  wireTabGroup("#in-season-tab-bar .tab-button", "inSeasonTab", "inSeasonTab");
  wireTabGroup("#wl-tab-bar .tab-button", "wlTab", "wlTab");

  weekInput.addEventListener("change", () => {
    state.week = weekInput.value ? Number(weekInput.value) : null;
    renderActive();
  });

  wlYearInput.value = state.wlYear;
  wlYearInput.addEventListener("change", () => {
    state.wlYear = wlYearInput.value ? Number(wlYearInput.value) : new Date().getFullYear();
    renderActive();
  });

  reloadLeagues();
}

init();
