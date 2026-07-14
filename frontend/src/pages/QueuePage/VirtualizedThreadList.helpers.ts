/** Cardinality breakpoint boundaries matching Tailwind. */
export const COL_BREAKPOINTS = {
  sm: 768,
  md: 1024,
  lg: 1280,
} as const

/**
 * Returns the number of grid columns to render for a given container width,
 * matching the Tailwind breakpoints used in the non-virtualized grid:
 *  `<768  → 1` (base)
 *  `<1024 → 2` (md)
 *  `<1280 → 2` (lg)
 *  `≥1280 → 3` (xl)
 *
 * Exported as a pure function for deterministic unit testing without a DOM.
 */
export function getColumnCount(width: number): number {
  if (width < COL_BREAKPOINTS.sm) return 1 // base / mobile
  if (width < COL_BREAKPOINTS.lg) return 2 // md + lg (both 2)
  return 3 // xl
}
