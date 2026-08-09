import { api } from "./api.js";

export async function renderScheduleTab(container, state) {
  const data = await api.getSchedule(state.season);
  container.appendChild(buildTable(data));
}

function buildTable(data) {
  const scrollWrap = document.createElement("div");
  scrollWrap.className = "grid-scroll";

  const table = document.createElement("table");
  table.className = "schedule-grid";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Team</th>" + data.weeks.map((w) => `<th>Wk ${w}</th>`).join("");
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const team of data.teams) {
    const row = document.createElement("tr");
    const teamCell = document.createElement("td");
    teamCell.textContent = team.team;
    teamCell.className = "schedule-team-label";
    row.appendChild(teamCell);

    for (const week of team.weeks) {
      row.appendChild(buildWeekCell(week));
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);

  scrollWrap.appendChild(table);
  return scrollWrap;
}

function buildWeekCell(week) {
  const cell = document.createElement("td");
  if (!week) {
    cell.className = "schedule-cell-empty";
    return cell;
  }
  if (week.bye) {
    cell.className = "schedule-cell-bye";
    cell.textContent = "BYE";
    return cell;
  }

  cell.textContent = week.is_home ? week.opponent : `@${week.opponent}`;
  if (week.difficulty === "easy") cell.className = "schedule-cell-easy";
  else if (week.difficulty === "hard") cell.className = "schedule-cell-hard";
  return cell;
}
