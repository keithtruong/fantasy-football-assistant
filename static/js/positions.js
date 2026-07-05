// Position color coding, carried over from the legacy spreadsheet's header fills (see CLAUDE.md).
export const POSITION_COLORS = {
  QB: "#2f7d3c",
  RB: "#2b5ea8",
  WR: "#b23b3b",
  TE: "#c65f9a",
  DST: "#b8860b",
  K: "#7449a6",
};

export function positionColor(position) {
  return POSITION_COLORS[position] || "#6b7280";
}
