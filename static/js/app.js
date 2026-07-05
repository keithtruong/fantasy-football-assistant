import { api } from "./api.js";
import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";
import { renderRostersTab } from "./rosters.js";
import { renderLeagueSettings } from "./leagueSettings.js";

const state = {
  leagueId: null,
  season: new Date().getFullYear(),
  scoringFormat: "full_ppr",
  activeSection: "draft_tool",
  activeTab: "draft",
};

const tabRenderers = {
  draft: renderDraftTab,
  grid: renderGridTab,
  rosters: renderRostersTab,
};

const tabContent = document.getElementById("tab-content");
const draftToolControls = document.getElementById("draft-tool-controls");
const tabBar = document.getElementById("tab-bar");
const leagueSelect = document.getElementById("league-select");

async function renderActive() {
  tabContent.innerHTML = "";
  if (state.activeSection === "league_settings") {
    draftToolControls.style.display = "none";
    tabBar.style.display = "none";
    await renderLeagueSettings(tabContent, reloadLeagues);
    return;
  }

  draftToolControls.style.display = "";
  tabBar.style.display = "";
  if (!state.leagueId) return;
  await tabRenderers[state.activeTab](tabContent, state, renderActive);
}

async function reloadLeagues() {
  const leagues = await api.getLeagues();
  const previousSelection = state.leagueId;
  leagueSelect.innerHTML = leagues.map((l) => `<option value="${l.league_id}">${l.name}</option>`).join("");

  const stillExists = leagues.some((l) => l.league_id === previousSelection);
  state.leagueId = stillExists ? previousSelection : leagues[0]?.league_id ?? null;
  if (state.leagueId != null) leagueSelect.value = state.leagueId;

  // Re-render whichever section is actually showing — this was the bug: it only
  // re-rendered the Draft Tool, so adding a league while ON League Settings never
  // reflected in the list until a full page reload.
  await renderActive();
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

  document.querySelectorAll(".tab-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeTab = btn.dataset.tab;
      renderActive();
    });
  });

  reloadLeagues();
}

init();
