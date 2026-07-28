import { renderDraftTab } from "./draft.js";
import { renderGridTab } from "./grid.js";

/** Side-by-side Draft + Grid, for wide monitors where both fit without tab-switching.
 * Each pane is just the existing tab renderer dropped into its own scoped column —
 * no shared state beyond what draft.js/grid.js already read off `state`. */
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

  wrap.appendChild(draftPane);
  wrap.appendChild(gridPane);
  container.appendChild(wrap);

  await Promise.all([
    renderDraftTab(draftPane, state, refresh),
    renderGridTab(gridPane, state, refresh),
  ]);
}
