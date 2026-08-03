import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";
import { renderTiersTab } from "./tiers.js";

/** Side-by-side Draft + Grid, for wide monitors where both fit without tab-switching.
 * Each pane is just the existing tab renderer dropped into its own scoped column —
 * no shared state beyond what draft.js/grid.js/tiers.js already read off `state`.
 * Tiers is stacked below Grid in the same pane (its own sub-container, appended
 * before the async renders fill in, so DOM order stays Grid-then-Tiers regardless
 * of which finishes fetching first). */
export async function renderCombinedTab(container, state, refresh) {
  const wrap = document.createElement("div");
  wrap.className = "combined-layout";

  const draftPane = document.createElement("div");
  draftPane.className = "combined-pane combined-pane-draft";
  const draftHeading = document.createElement("h3");
  draftHeading.className = "combined-pane-heading";
  draftHeading.textContent = "Draft";
  draftPane.appendChild(draftHeading);

  const gridPane = document.createElement("div");
  gridPane.className = "combined-pane combined-pane-grid";
  const gridHeading = document.createElement("h3");
  gridHeading.className = "combined-pane-heading";
  gridHeading.textContent = "Grid";
  gridPane.appendChild(gridHeading);

  const gridContent = document.createElement("div");
  gridPane.appendChild(gridContent);

  const tiersHeading = document.createElement("h3");
  tiersHeading.className = "combined-pane-heading combined-tiers-heading";
  tiersHeading.textContent = "Tiers";
  gridPane.appendChild(tiersHeading);

  const tiersContent = document.createElement("div");
  gridPane.appendChild(tiersContent);

  wrap.appendChild(draftPane);
  wrap.appendChild(gridPane);
  container.appendChild(wrap);

  await Promise.all([
    renderDraftTab(draftPane, state, refresh),
    renderGridTab(gridContent, state, refresh),
    renderTiersTab(tiersContent, state),
  ]);
}
