import { api } from "./api.js";
import { positionColor } from "./positions.js";

const CORE_POSITIONS = ["QB", "RB", "WR", "TE"];

export async function renderRostersTab(container, state) {
  const [teams, settings, rankings] = await Promise.all([
    api.getTeams(state.leagueId),
    api.getSettings(state.leagueId),
    api.getRankings(state.leagueId, state.scoringFormat, state.season),
  ]);

  const rankByPlayerId = new Map(rankings.map((r) => [r.player_id, r.rank]));
  const rosterSlotCounts = Object.fromEntries(
    settings.roster_slots.map((s) => [s.slot_name, s.slot_count])
  );
  const teamsByDraftPosition = [...teams].sort(
    (a, b) => (a.draft_position || 0) - (b.draft_position || 0)
  );

  const strengthByTeamAndPosition = computeRelativeStrength(teamsByDraftPosition, rankByPlayerId);

  const scrollWrap = document.createElement("div");
  scrollWrap.className = "rosters-scroll";
  for (const team of teamsByDraftPosition) {
    scrollWrap.appendChild(buildTeamCard(team, rosterSlotCounts, strengthByTeamAndPosition));
  }
  container.appendChild(scrollWrap);
}

/** Team's relative rank at each position = average draft rank of that team's
 * players there, ranked against every other team (1 = strongest at that position). */
function computeRelativeStrength(teams, rankByPlayerId) {
  const result = new Map(); // team_id -> { position: relativeRank }

  for (const position of CORE_POSITIONS) {
    const averages = teams.map((team) => {
      const ranks = team.roster
        .filter((p) => p.position === position)
        .map((p) => rankByPlayerId.get(p.player_id))
        .filter((r) => r != null);
      const avg = ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : null;
      return { team_id: team.team_id, avg };
    });

    const ranked = averages.filter((a) => a.avg != null).sort((a, b) => a.avg - b.avg);
    ranked.forEach((entry, index) => {
      if (!result.has(entry.team_id)) result.set(entry.team_id, {});
      result.get(entry.team_id)[position] = index + 1;
    });
  }
  return result;
}

function buildTeamCard(team, rosterSlotCounts, strengthByTeamAndPosition) {
  const card = document.createElement("div");
  card.className = "team-card";
  if (team.is_mine) card.classList.add("my-team-card");

  const heading = document.createElement("h3");
  heading.textContent = team.team_name;
  card.appendChild(heading);

  const strength = strengthByTeamAndPosition.get(team.team_id) || {};

  for (const position of CORE_POSITIONS) {
    const players = team.roster
      .filter((p) => p.position === position)
      .sort((a, b) => (a.pick_number || 0) - (b.pick_number || 0));

    const section = document.createElement("div");
    section.className = "team-card-position";

    const label = document.createElement("div");
    label.className = "team-card-position-label";
    const chip = document.createElement("span");
    chip.className = "position-chip";
    chip.textContent = position;
    chip.style.backgroundColor = positionColor(position);
    label.appendChild(chip);
    if (strength[position]) {
      const rankText = document.createElement("span");
      rankText.className = "position-relative-rank";
      rankText.textContent = `#${strength[position]} in league`;
      label.appendChild(rankText);
    }
    section.appendChild(label);

    const starterCount = rosterSlotCounts[position] || 0;
    players.forEach((player, index) => {
      const line = document.createElement("div");
      line.textContent = player.full_name;
      line.className = index >= starterCount ? "roster-player-bench" : "roster-player-starter";
      section.appendChild(line);
    });

    card.appendChild(section);
  }

  return card;
}
