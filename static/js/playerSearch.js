import { api } from "./api.js";

/** Builds a debounced search input + results dropdown, calling onSelect(player) on click. */
export function buildPlayerSearch({ leagueId, season, placeholder, onSelect }) {
  const wrap = document.createElement("div");
  wrap.className = "search-row";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = placeholder || "Type a player name…";
  input.className = "player-search";
  wrap.appendChild(input);

  const results = document.createElement("ul");
  results.className = "search-results";
  wrap.appendChild(results);

  let debounceHandle;
  input.addEventListener("input", () => {
    clearTimeout(debounceHandle);
    const query = input.value;
    debounceHandle = setTimeout(async () => {
      results.innerHTML = "";
      if (query.trim().length < 2) return;
      const matches = await api.searchPlayers(query, leagueId, season);
      for (const player of matches) {
        const li = document.createElement("li");
        li.textContent = `${player.full_name} (${player.position || "?"}${player.nfl_team ? " " + player.nfl_team : ""})`;
        li.addEventListener("click", () => onSelect(player));
        results.appendChild(li);
      }
    }, 200);
  });

  return wrap;
}
