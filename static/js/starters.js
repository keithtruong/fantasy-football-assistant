import { api } from "./api.js";
import { positionColor } from "./positions.js";

// Fixed display order for the slot list — matches how a lineup card reads
// top-to-bottom (dedicated positions, then the flex slots the algorithm fills
// from whatever's left over). Any other slot name the backend returns (a
// league with an unusual configured slot) is appended after these in
// whatever order it comes back in, rather than dropped.
const SLOT_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "DST", "K"];

// Mirrors ffassistant.starters' eligibility sets — used to decide which extra
// rank badges a bench player's row can show.
const FLEX_ELIGIBLE = new Set(["RB", "WR", "TE"]);
const SUPERFLEX_ELIGIBLE = new Set(["QB", "RB", "WR", "TE"]);

export async function renderStartersTab(container, state) {
  const data = await api.getInSeason(state.leagueId, "starters", state.season, state.week);

  const wrap = el("div", "in-season-view");

  const heading = document.createElement("h3");
  heading.textContent = "Optimal Starting Lineup";
  wrap.appendChild(heading);

  const slotList = el("ol", "starters-slot-list");
  for (const slot of sortedSlots(data.slots)) {
    slotList.appendChild(buildSlotRow(slot));
  }
  wrap.appendChild(slotList);

  if (data.bench.length > 0) {
    // Only show a FLEX/SUPER_FLEX rank badge if this league actually has that
    // slot — the ranks exist in the data regardless, but they're only
    // meaningful to a bench player's path back into the lineup if the slot
    // that would use them actually exists here.
    const slotNames = new Set(data.slots.map((s) => s.slot_name));
    const hasFlex = slotNames.has("FLEX");
    const hasSuperFlex = slotNames.has("SUPER_FLEX");

    const benchHeading = document.createElement("h4");
    benchHeading.textContent = "Bench";
    wrap.appendChild(benchHeading);

    const benchList = el("ul", "starters-bench-list");
    for (const player of data.bench) {
      benchList.appendChild(buildBenchRow(player, hasFlex, hasSuperFlex));
    }
    wrap.appendChild(benchList);
  }

  container.appendChild(wrap);
}

function sortedSlots(slots) {
  return [...slots].sort((a, b) => {
    const ai = SLOT_ORDER.indexOf(a.slot_name);
    const bi = SLOT_ORDER.indexOf(b.slot_name);
    if (ai === -1 && bi === -1) return 0;
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
}

function buildSlotRow(slot) {
  const li = document.createElement("li");
  li.className = "starters-slot";

  const chip = el("span", "position-chip");
  chip.textContent = slot.slot_name.replace("_", " ");
  chip.style.backgroundColor = positionColor(slot.slot_name);
  li.appendChild(chip);

  if (slot.player) {
    li.appendChild(buildPlayerLine(slot.player));
  } else {
    const empty = el("span", "in-season-empty");
    empty.textContent = " No eligible player";
    li.appendChild(empty);
  }

  return li;
}

// Unlike a slot row (one rank — whichever list the player was actually
// picked from), a bench row shows every rank that could bring this player
// back into the lineup: their own position, plus FLEX/SUPER_FLEX combined
// ranks when this league has those slots and the player is eligible.
function buildBenchRow(player, hasFlex, hasSuperFlex) {
  const li = document.createElement("li");

  const chip = el("span", "position-chip");
  chip.textContent = player.position;
  chip.style.backgroundColor = positionColor(player.position);
  li.appendChild(chip);

  li.appendChild(buildRankBadge(player.position, player.rank));
  if (hasFlex && FLEX_ELIGIBLE.has(player.position)) {
    li.appendChild(buildRankBadge("FLEX", player.flex_rank));
  }
  if (hasSuperFlex && SUPERFLEX_ELIGIBLE.has(player.position)) {
    li.appendChild(buildRankBadge("SFLX", player.op_rank));
  }

  li.appendChild(document.createTextNode(" " + player.full_name));

  if (player.status && player.status !== "healthy") {
    const badge = el("span", "status-badge");
    badge.textContent = player.status;
    li.appendChild(badge);
  }

  return li;
}

function buildRankBadge(label, rank) {
  const span = el("span", "in-season-rank");
  span.textContent = rank != null ? `${label} #${rank}` : `${label} Unranked`;
  return span;
}

function buildPlayerLine(player) {
  const frag = document.createDocumentFragment();

  const rankSpan = el("span", "in-season-rank");
  rankSpan.textContent = player.rank != null ? `#${player.rank}` : "Unranked";
  frag.appendChild(rankSpan);

  frag.appendChild(document.createTextNode(" " + player.full_name));

  if (player.status && player.status !== "healthy") {
    const badge = el("span", "status-badge");
    badge.textContent = player.status;
    frag.appendChild(badge);
  }

  return frag;
}

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}
