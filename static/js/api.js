// Thin fetch wrapper for the local Flask API. No build step — plain ES module.

async function request(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.description || `Request failed: ${resp.status}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export const api = {
  getLeagues: (includeInactive = false) =>
    request(`/api/leagues${includeInactive ? "?include_inactive=1" : ""}`),
  createLeague: (payload) =>
    request("/api/leagues", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) }),
  updateLeague: (leagueId, payload) =>
    request(`/api/leagues/${leagueId}`, { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(payload) }),
  deleteLeague: (leagueId) => request(`/api/leagues/${leagueId}`, { method: "DELETE" }),
  resyncLeague: (leagueId, season) =>
    request(`/api/leagues/${leagueId}/sync`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ season }),
    }),
  updateTeam: (leagueId, teamId, payload) =>
    request(`/api/leagues/${leagueId}/teams/${teamId}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),
  getSettings: (leagueId) => request(`/api/leagues/${leagueId}/settings`),
  getTeams: (leagueId) => request(`/api/leagues/${leagueId}/teams`),
  getRankings: (leagueId, scoringFormat, season) =>
    request(`/api/leagues/${leagueId}/rankings?scoring_format=${scoringFormat}&season=${season}`),
  getDraftPicks: (leagueId, season) =>
    request(`/api/leagues/${leagueId}/draft_picks?season=${season}`),
  recordPick: (leagueId, playerId, season) =>
    request(`/api/leagues/${leagueId}/draft_picks`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ player_id: playerId, season }),
    }),
  editPick: (leagueId, pickId, playerId) =>
    request(`/api/leagues/${leagueId}/draft_picks/${pickId}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ player_id: playerId }),
    }),
  undoPick: (leagueId, pickId) =>
    request(`/api/leagues/${leagueId}/draft_picks/${pickId}`, { method: "DELETE" }),
  clearPicks: (leagueId, season) =>
    request(`/api/leagues/${leagueId}/draft_picks?season=${season}`, { method: "DELETE" }),
  searchPlayers: (query, leagueId, season) =>
    request(`/api/players/search?q=${encodeURIComponent(query)}&league_id=${leagueId}&season=${season}`),
  setManualTag: (playerId, tag) =>
    request(`/api/players/${playerId}/manual_tag`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ tag }),
    }),
  setRoleTag: (playerId, tag) =>
    request(`/api/players/${playerId}/role_tag`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ tag }),
    }),
  getInSeason: (leagueId, view, season, week) =>
    request(
      `/api/leagues/${leagueId}/in_season?view=${view}&season=${season}` + (week ? `&week=${week}` : "")
    ),
  getExposure: () => request("/api/exposure"),
  getSchedule: (season) => request(`/api/schedule?season=${season}`),
  getWlLeagueHistory: () => request("/api/wl/league_history"),
  getWlGames: (year) => request(`/api/wl/games?year=${year}`),
  getWlWeekly: (year) => request(`/api/wl/weekly?year=${year}`),
  getWlLeagues: (year) => request(`/api/wl/leagues?year=${year}`),
  getWlCloseGames: (year) => request(`/api/wl/close_games?year=${year}`),
  getWlAllTime: () => request("/api/wl/all_time"),
  getWlFinishes: () => request("/api/wl/finishes"),
  putWlMatchup: (payload) =>
    request("/api/wl/matchups", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(payload) }),
  syncRankings: (season, scoringFormat) =>
    request("/api/rankings/sync", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ season, scoring_format: scoringFormat }),
    }),
  getRankingsSyncStatus: (season, scoringFormat) =>
    request(`/api/rankings/sync_status?season=${season}&scoring_format=${scoringFormat}`),
};
