import { api } from "./api.js";
import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";
import { renderCombinedTab } from "./combined.js";
import { renderTiersTab } from "./tiers.js";
import { renderRostersTab } from "./rosters.js";
import { renderScheduleTab } from "./schedule.js";
import { renderPostDraftTab } from "./postDraft.js";
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
  draftPositionFilter: new Set(),
};

const tabRenderers = {
  draft: renderDraftTab,
  grid: renderGridTab,
  combined: renderCombinedTab,
  tiers: renderTiersTab,
  rosters: renderRostersTab,
  schedule: renderScheduleTab,
  post_draft: renderPostDraftTab,
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
const scoringSelect = document.getElementById("scoring-format-select");
const refreshWeeklyRankingsButton = document.getElementById("refresh-weekly-rankings-button");
const weeklyRankingsSyncStatus = document.getElementById("weekly-rankings-sync-status");
const refreshRosRankingsButton = document.getElementById("refresh-ros-rankings-button");
const rosRankingsSyncStatus = document.getElementById("ros-rankings-sync-status");
const refreshNewsButton = document.getElementById("refresh-news-button");
const newsSyncStatus = document.getElementById("news-sync-status");

let leaguesById = {};

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
  leaguesById = Object.fromEntries(leagues.map((l) => [l.league_id, l]));
  const previousSelection = state.leagueId;
  leagueSelect.innerHTML = leagues.map((l) => `<option value="${l.league_id}">${l.name}</option>`).join("");

  const stillExists = leagues.some((l) => l.league_id === previousSelection);
  state.leagueId = stillExists ? previousSelection : leagues[0]?.league_id ?? null;
  if (state.leagueId != null) {
    leagueSelect.value = state.leagueId;
    applyLeagueScoringFormat();
  }

  // Re-render whichever section is actually showing — adding a league while ON
  // League Settings must reflect in the list without needing a full page reload.
  await renderActive();
}

// Prefills the week input from the backend's current_week() (see the Season
// panel in League Settings) so the Weekly tab and its sync status reflect
// reality on load instead of staying blank until someone types a number in —
// still just a starting value, same as a manual entry would be, so nothing
// stops overriding it afterward. Also reorders the section nav by the same
// signal (see applySectionNavOrder) so whichever section is most relevant
// right now leads.
async function initCurrentWeek() {
  try {
    const seasonInfo = await api.getSeason(state.season);
    applySectionNavOrder(seasonInfo.current_week != null);
    if (seasonInfo.current_week != null) {
      state.week = seasonInfo.current_week;
      weekInput.value = state.week;
    }
  } catch {
    // Non-critical — week input just stays blank for manual entry, nav stays
    // in its preseason (Draft Tool-first) default order.
  }
}

// Draft Tool matters most before the season starts, In-season matters most
// once it has — Exposure is relevant year-round either way, so it stays the
// pivot in the middle rather than moving. League Settings/W-L are low-frequency
// admin/reference views, always last regardless.
function applySectionNavOrder(seasonActive) {
  const nav = document.getElementById("section-nav");
  const order = seasonActive
    ? ["in_season", "exposure", "draft_tool", "league_settings", "wl"]
    : ["draft_tool", "exposure", "in_season", "league_settings", "wl"];
  const buttonsBySection = Object.fromEntries(
    Array.from(nav.querySelectorAll(".section-button")).map((btn) => [btn.dataset.section, btn])
  );
  for (const section of order) {
    nav.appendChild(buttonsBySection[section]);
  }
}

// Defaults the scoring-format picker to whatever this league's own settings imply
// (see leagues API's derived `scoring_format`) so switching to e.g. a superflex
// league surfaces superflex rankings without a manual dropdown change first.
// Still just sets the same dropdown/state a manual change would — nothing stops
// overriding it afterward if the derived guess is wrong for a given league.
function applyLeagueScoringFormat() {
  const scoringFormat = leaguesById[state.leagueId]?.scoring_format;
  if (!scoringFormat) return;
  state.scoringFormat = scoringFormat;
  scoringSelect.value = scoringFormat;
  refreshSyncStatus();
  refreshRosSyncStatus();
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

async function refreshWeeklySyncStatus() {
  if (!state.week) {
    weeklyRankingsSyncStatus.textContent = "";
    return;
  }
  try {
    const status = await api.getWeeklyRankingsSyncStatus(state.season, state.week);
    weeklyRankingsSyncStatus.textContent = formatSyncedAt(status.synced_at);
    weeklyRankingsSyncStatus.className = "rankings-sync-status";
  } catch {
    // Non-critical — leave whatever status text was already showing.
  }
}

async function refreshRosSyncStatus() {
  try {
    const status = await api.getRosRankingsSyncStatus(state.season, state.scoringFormat);
    rosRankingsSyncStatus.textContent = formatSyncedAt(status.synced_at);
    rosRankingsSyncStatus.className = "rankings-sync-status";
  } catch {
    // Non-critical — leave whatever status text was already showing.
  }
}

async function refreshNewsSyncStatus() {
  try {
    const status = await api.getNewsSyncStatus();
    newsSyncStatus.textContent = formatSyncedAt(status.synced_at);
    newsSyncStatus.className = "rankings-sync-status";
  } catch {
    // Non-critical — leave whatever status text was already showing.
  }
}

// Only the active in-season sub-tab's refresh control is relevant — Schedule
// needs none of these, and showing weekly's and ROS's buttons together just
// invites clicking the wrong one for the view you're looking at. Player news
// isn't week/format-scoped, so it's shown for either Weekly or ROS.
function updateInSeasonControlsVisibility() {
  const showWeekly = state.inSeasonTab === "weekly";
  const showRos = state.inSeasonTab === "ros";
  refreshWeeklyRankingsButton.style.display = showWeekly ? "" : "none";
  weeklyRankingsSyncStatus.style.display = showWeekly ? "" : "none";
  refreshRosRankingsButton.style.display = showRos ? "" : "none";
  rosRankingsSyncStatus.style.display = showRos ? "" : "none";
  const showNews = showWeekly || showRos;
  refreshNewsButton.style.display = showNews ? "" : "none";
  newsSyncStatus.style.display = showNews ? "" : "none";
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
      if (state.activeSection === "in_season") {
        updateInSeasonControlsVisibility();
        refreshWeeklySyncStatus();
        refreshRosSyncStatus();
        refreshNewsSyncStatus();
      }
    });
  });

  leagueSelect.addEventListener("change", () => {
    state.leagueId = Number(leagueSelect.value);
    applyLeagueScoringFormat();
    renderActive();
  });

  scoringSelect.value = state.scoringFormat;
  scoringSelect.addEventListener("change", () => {
    state.scoringFormat = scoringSelect.value;
    renderActive();
    refreshSyncStatus();
    refreshRosSyncStatus();
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

  refreshWeeklyRankingsButton.addEventListener("click", async () => {
    if (!state.week) {
      weeklyRankingsSyncStatus.textContent = "Enter a week number first";
      weeklyRankingsSyncStatus.className = "rankings-sync-status rankings-sync-error";
      return;
    }
    refreshWeeklyRankingsButton.disabled = true;
    weeklyRankingsSyncStatus.textContent = "Refreshing…";
    weeklyRankingsSyncStatus.className = "rankings-sync-status";
    try {
      const result = await api.syncWeeklyRankings(state.season, state.week);
      const unresolvedNote = result.unresolved_count ? `, ${result.unresolved_count} unresolved` : "";
      weeklyRankingsSyncStatus.textContent =
        `${formatSyncedAt(result.synced_at)} — ${result.player_count} players${unresolvedNote}`;
      weeklyRankingsSyncStatus.className = result.unresolved_count
        ? "rankings-sync-status rankings-sync-warning"
        : "rankings-sync-status";
      await renderActive();
    } catch (err) {
      weeklyRankingsSyncStatus.textContent = err.message;
      weeklyRankingsSyncStatus.className = "rankings-sync-status rankings-sync-error";
    } finally {
      refreshWeeklyRankingsButton.disabled = false;
    }
  });

  refreshRosRankingsButton.addEventListener("click", async () => {
    refreshRosRankingsButton.disabled = true;
    rosRankingsSyncStatus.textContent = "Refreshing…";
    rosRankingsSyncStatus.className = "rankings-sync-status";
    try {
      const result = await api.syncRosRankings(state.season, state.scoringFormat);
      const unresolvedNote = result.unresolved_count ? `, ${result.unresolved_count} unresolved` : "";
      rosRankingsSyncStatus.textContent =
        `${formatSyncedAt(result.synced_at)} — ${result.player_count} players${unresolvedNote}`;
      rosRankingsSyncStatus.className = result.unresolved_count
        ? "rankings-sync-status rankings-sync-warning"
        : "rankings-sync-status";
      await renderActive();
    } catch (err) {
      rosRankingsSyncStatus.textContent = err.message;
      rosRankingsSyncStatus.className = "rankings-sync-status rankings-sync-error";
    } finally {
      refreshRosRankingsButton.disabled = false;
    }
  });

  refreshNewsButton.addEventListener("click", async () => {
    refreshNewsButton.disabled = true;
    newsSyncStatus.textContent = "Refreshing…";
    newsSyncStatus.className = "rankings-sync-status";
    try {
      const result = await api.syncPlayerNews();
      newsSyncStatus.textContent =
        `${formatSyncedAt(result.synced_at)} — ${result.headline_count} headlines, ${result.player_count} players`;
      newsSyncStatus.className = "rankings-sync-status";
      await renderActive();
    } catch (err) {
      newsSyncStatus.textContent = err.message;
      newsSyncStatus.className = "rankings-sync-status rankings-sync-error";
    } finally {
      refreshNewsButton.disabled = false;
    }
  });

  wireTabGroup("#tab-bar .tab-button", "tab", "activeTab");
  wireTabGroup("#in-season-tab-bar .tab-button", "inSeasonTab", "inSeasonTab");
  wireTabGroup("#wl-tab-bar .tab-button", "wlTab", "wlTab");

  document.querySelectorAll("#in-season-tab-bar .tab-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      updateInSeasonControlsVisibility();
      refreshWeeklySyncStatus();
      refreshRosSyncStatus();
      refreshNewsSyncStatus();
    });
  });
  updateInSeasonControlsVisibility();

  weekInput.addEventListener("change", () => {
    state.week = weekInput.value ? Number(weekInput.value) : null;
    renderActive();
    refreshWeeklySyncStatus();
  });

  wlYearInput.value = state.wlYear;
  wlYearInput.addEventListener("change", () => {
    state.wlYear = wlYearInput.value ? Number(wlYearInput.value) : new Date().getFullYear();
    renderActive();
  });

  Promise.all([reloadLeagues(), initCurrentWeek()]).then(() => {
    refreshWeeklySyncStatus();
    refreshRosSyncStatus();
    refreshNewsSyncStatus();
  });
}

init();
