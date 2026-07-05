import { api } from "./api.js";
import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";
import { renderRostersTab } from "./rosters.js";
import { renderLeagueSettings } from "./leagueSettings.js";
import { renderInSeasonView } from "./inSeason.js";

const state = {
  leagueId: null,
  season: new Date().getFullYear(),
  scoringFormat: "full_ppr",
  activeSection: "draft_tool",
  activeTab: "draft",
  inSeasonTab: "weekly",
  week: null,
};

const tabRenderers = {
  draft: renderDraftTab,
  grid: renderGridTab,
  rosters: renderRostersTab,
};

const tabContent = document.getElementById("tab-content");
const leagueSelectRow = document.getElementById("league-select-row");
const draftToolControls = document.getElementById("draft-tool-controls");
const tabBar = document.getElementById("tab-bar");
const inSeasonControls = document.getElementById("in-season-controls");
const inSeasonTabBar = document.getElementById("in-season-tab-bar");
const leagueSelect = document.getElementById("league-select");
const weekInput = document.getElementById("in-season-week-input");

const SECTION_ROWS = {
  draft_tool: [leagueSelectRow, draftToolControls, tabBar],
  in_season: [leagueSelectRow, inSeasonControls, inSeasonTabBar],
  league_settings: [],
};

function setVisibleRows(visibleRows) {
  const all = [leagueSelectRow, draftToolControls, tabBar, inSeasonControls, inSeasonTabBar];
  for (const row of all) {
    row.style.display = visibleRows.includes(row) ? "" : "none";
  }
}

async function renderActive() {
  tabContent.innerHTML = "";
  setVisibleRows(SECTION_ROWS[state.activeSection]);

  if (state.activeSection === "league_settings") {
    await renderLeagueSettings(tabContent, reloadLeagues);
    return;
  }

  if (!state.leagueId) return;

  if (state.activeSection === "in_season") {
    await renderInSeasonView(tabContent, state, renderActive);
    return;
  }

  await tabRenderers[state.activeTab](tabContent, state, renderActive);
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
  });

  wireTabGroup("#tab-bar .tab-button", "tab", "activeTab");
  wireTabGroup("#in-season-tab-bar .tab-button", "inSeasonTab", "inSeasonTab");

  weekInput.addEventListener("change", () => {
    state.week = weekInput.value ? Number(weekInput.value) : null;
    renderActive();
  });

  reloadLeagues();
}

init();
