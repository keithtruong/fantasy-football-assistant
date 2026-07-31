import { api } from "./api.js";

const PLAYOFF_LABELS = {
  semifinal: "Semifinal",
  final: "Final",
  third_place: "3rd Place",
};

export async function renderWlView(container, state) {
  const view = state.wlTab; // "games" | "weekly" | "leagues" | "close_games" | "all_time"
  const wrap = el("div", "wl-view");

  if (view === "games") {
    wrap.appendChild(await buildGamesView(state.wlYear, () => renderWlView(container, state)));
  } else if (view === "weekly") {
    wrap.appendChild(await buildWeeklyView(state.wlYear));
  } else if (view === "leagues") {
    wrap.appendChild(await buildLeaguesView(state.wlYear));
  } else if (view === "close_games") {
    wrap.appendChild(await buildCloseGamesView(state.wlYear));
  } else if (view === "all_time") {
    wrap.appendChild(await buildAllTimeView());
  }

  container.appendChild(wrap);
}

// ---- Games: one card per league, weeks as rows, click a week to edit ----

async function buildGamesView(year, refresh) {
  const leagues = await api.getWlGames(year);

  const scrollWrap = el("div", "wl-games-scroll");
  if (leagues.length === 0) {
    const empty = document.createElement("p");
    empty.className = "wl-empty";
    empty.textContent = "No leagues found for this year.";
    scrollWrap.appendChild(empty);
    return scrollWrap;
  }

  for (const league of leagues) {
    scrollWrap.appendChild(buildLeagueGameCard(league, year, refresh));
  }
  return scrollWrap;
}

function buildLeagueGameCard(league, year, refresh) {
  const card = el("div", "wl-game-card");

  const heading = document.createElement("h3");
  heading.textContent = league.name;
  card.appendChild(heading);

  const table = el("table", "wl-games-table");
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Wk</th><th>Outcome</th><th>PF</th><th>PA</th><th>Diff</th><th>Playoffs</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const weekData of league.weeks) {
    tbody.appendChild(buildWeekRow(league.league_history_id, weekData, year, refresh));
  }
  table.appendChild(tbody);

  const tfoot = document.createElement("tfoot");
  const totals = league.totals;
  const totalRow = document.createElement("tr");
  totalRow.innerHTML =
    `<td>Total</td><td>${totals.wins}-${totals.losses}-${totals.ties}</td>` +
    `<td>${totals.points_for.toFixed(1)}</td><td>${totals.points_against.toFixed(1)}</td>` +
    `<td colspan="2"></td>`;
  tfoot.appendChild(totalRow);
  table.appendChild(tfoot);

  card.appendChild(table);
  return card;
}

function buildWeekRow(leagueHistoryId, weekData, year, refresh) {
  const row = document.createElement("tr");
  if (weekData.outcome == null) row.classList.add("wl-week-empty");

  renderWeekRowContent(row, weekData);

  row.addEventListener("click", () => {
    if (row.querySelector(".wl-edit-form")) return;
    openWeekEditForm(row, leagueHistoryId, weekData, year, refresh);
  });

  return row;
}

function renderWeekRowContent(row, weekData) {
  row.innerHTML = "";

  const outcomeCell = td(weekData.outcome || "—");
  if (weekData.outcome) outcomeCell.classList.add(`wl-outcome-${weekData.outcome}`);

  const diffCell = td(weekData.differential != null ? weekData.differential.toFixed(1) : "—");
  applyDiffClass(diffCell, weekData.differential);

  row.append(
    td(weekData.week),
    outcomeCell,
    td(weekData.points_for != null ? weekData.points_for.toFixed(1) : "—"),
    td(weekData.points_against != null ? weekData.points_against.toFixed(1) : "—"),
    diffCell,
    td(PLAYOFF_LABELS[weekData.playoff_round] || "")
  );
}

function applyDiffClass(cell, value) {
  if (value == null || value === 0) return;
  cell.classList.add(value > 0 ? "wl-diff-positive" : "wl-diff-negative");
}

function openWeekEditForm(row, leagueHistoryId, weekData, year, refresh) {
  row.innerHTML = "";
  const cell = document.createElement("td");
  cell.colSpan = 6;
  cell.className = "wl-edit-form";

  const pfInput = document.createElement("input");
  pfInput.type = "number";
  pfInput.step = "0.01";
  pfInput.placeholder = "PF";
  pfInput.value = weekData.points_for ?? "";

  const paInput = document.createElement("input");
  paInput.type = "number";
  paInput.step = "0.01";
  paInput.placeholder = "PA";
  paInput.value = weekData.points_against ?? "";

  const playoffSelect = document.createElement("select");
  const options = { "": "—", semifinal: "Semifinal", final: "Final", third_place: "3rd Place" };
  for (const [value, label] of Object.entries(options)) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    if ((weekData.playoff_round || "") === value) opt.selected = true;
    playoffSelect.appendChild(opt);
  }

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "wl-save-button";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", async () => {
    if (pfInput.value === "" || paInput.value === "") return;
    await api.putWlMatchup({
      league_history_id: leagueHistoryId,
      season: year,
      week: weekData.week,
      points_for: Number(pfInput.value),
      points_against: Number(paInput.value),
      playoff_round: playoffSelect.value || null,
    });
    refresh();
  });

  cell.append(pfInput, paInput, playoffSelect, saveBtn);
  row.appendChild(cell);
  pfInput.focus();
}

// ---- Weekly: net games-above-even across all leagues, plus cumulative ----

async function buildWeeklyView(year) {
  const weeks = await api.getWlWeekly(year);

  const table = el("table", "wl-data-table wl-weekly-table");
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Week</th><th>W</th><th>L</th><th>T</th><th>PF</th><th>PA</th><th>Diff</th><th>Net</th><th>Cumulative</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const week of weeks) {
    const diff = week.points_for - week.points_against;
    const diffCell = td(diff.toFixed(1));
    applyDiffClass(diffCell, diff);

    const row = document.createElement("tr");
    row.append(
      td(week.week),
      td(week.wins),
      td(week.losses),
      td(week.ties),
      td(week.points_for.toFixed(1)),
      td(week.points_against.toFixed(1)),
      diffCell,
      td(formatSigned(week.net_games_above_even)),
      td(formatSigned(week.cumulative_net))
    );
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

// ---- Leagues: one row per league for the year ----

async function buildLeaguesView(year) {
  const leagues = await api.getWlLeagues(year);

  const table = el("table", "wl-data-table wl-leagues-table");
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>League</th><th>W</th><th>L</th><th>T</th><th>Buy-in</th><th>Max</th><th>Actual</th><th>Finish</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const league of leagues) {
    const row = document.createElement("tr");
    row.append(
      td(league.name),
      td(league.wins),
      td(league.losses),
      td(league.ties),
      td(formatMoney(league.buy_in)),
      td(formatMoney(league.max_payout)),
      td(formatMoney(league.actual_payout)),
      td(league.finish_position ?? "—")
    );
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

// ---- Close Games: fixed <6pt margin, split into wins vs. losses ----

async function buildCloseGamesView(year) {
  const games = await api.getWlCloseGames(year);
  const wrap = el("div", "wl-close-games-wrap");

  wrap.appendChild(buildCloseGamesTable("Close Wins", games.filter((g) => g.outcome === "W"), "wl-outcome-W"));
  wrap.appendChild(buildCloseGamesTable("Close Losses", games.filter((g) => g.outcome === "L"), "wl-outcome-L"));
  return wrap;
}

function buildCloseGamesTable(title, games, outcomeClass) {
  const section = el("div", "wl-close-games-section");
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.appendChild(heading);

  const table = el("table", "wl-data-table wl-close-games-table");
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>League</th><th>Week</th><th>Margin</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  if (games.length === 0) {
    const row = document.createElement("tr");
    const cell = td(`No ${title.toLowerCase()} within 6 points this year.`);
    cell.colSpan = 3;
    row.appendChild(cell);
    tbody.appendChild(row);
  }
  for (const game of games) {
    const row = document.createElement("tr");
    const marginCell = td(game.margin.toFixed(1));
    marginCell.classList.add(outcomeClass);
    row.append(td(game.league_name), td(game.week), marginCell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

// ---- All Years: one rollup row per league, spans every season ----

async function buildAllTimeView() {
  const [leagues, finishes] = await Promise.all([api.getWlAllTime(), api.getWlFinishes()]);

  const wrap = el("div", "wl-all-time-wrap");

  const table = el("table", "wl-data-table wl-all-time-table");
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>League</th><th>W</th><th>L</th><th>T</th><th>Win %</th><th>Years</th>" +
    "<th>1st</th><th>2nd</th><th>3rd</th><th>PF</th><th>PA</th><th>Total Buy-in</th><th>Total Payout</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const league of leagues) {
    const row = document.createElement("tr");
    row.append(
      td(league.name),
      td(league.wins),
      td(league.losses),
      td(league.ties),
      td(league.win_pct != null ? (league.win_pct * 100).toFixed(1) + "%" : "—"),
      td(league.years_played),
      finishTd(league.firsts, league.first_years),
      finishTd(league.seconds, league.second_years),
      finishTd(league.thirds, league.third_years),
      td(league.points_for != null ? league.points_for.toFixed(1) : "—"),
      td(league.points_against != null ? league.points_against.toFixed(1) : "—"),
      td(formatMoney(league.total_buy_in)),
      td(formatMoney(league.total_actual_payout))
    );
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  wrap.appendChild(buildFinishesGrid(finishes));
  return wrap;
}

// ---- Finishes grid: league x year, gold/silver/bronze for 1st/2nd/3rd ----

function buildFinishesGrid(finishes) {
  const scrollWrap = el("div", "wl-finishes-scroll");

  const heading = document.createElement("h3");
  heading.textContent = "Finishes by Year";
  scrollWrap.appendChild(heading);

  const table = el("table", "wl-data-table wl-finishes-table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.appendChild(document.createElement("th")).textContent = "League";
  for (const year of finishes.years) {
    const th = document.createElement("th");
    th.textContent = year;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const league of finishes.leagues) {
    const row = document.createElement("tr");
    row.appendChild(td(league.name));
    for (const year of finishes.years) {
      row.appendChild(finishCell(league.finishes[year]));
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  scrollWrap.appendChild(table);

  return scrollWrap;
}

function finishCell(place) {
  const cell = document.createElement("td");
  if (place == null) {
    cell.textContent = "";
    cell.className = "wl-finish-none";
    return cell;
  }
  cell.textContent = place;
  cell.className =
    place === 1 ? "wl-finish-gold" : place === 2 ? "wl-finish-silver" : place === 3 ? "wl-finish-bronze" : "";
  return cell;
}

function formatSigned(n) {
  return n > 0 ? `+${n}` : `${n}`;
}

function formatMoney(n) {
  return n != null ? `$${n}` : "—";
}

function td(content) {
  const cell = document.createElement("td");
  cell.textContent = content;
  return cell;
}

// A finish count (1st/2nd/3rd) with the specific years on hover — the raw
// count alone doesn't say when.
function finishTd(count, years) {
  const cell = td(count);
  if (years && years.length) {
    cell.title = years.join(", ");
    cell.classList.add("wl-finish-cell");
  }
  return cell;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
