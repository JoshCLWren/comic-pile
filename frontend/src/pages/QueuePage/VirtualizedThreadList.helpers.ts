/** Height of a single card in pixels. */
export const CARD_HEIGHT = 160

/** Vertical gap between rows (matches Tailwind `gap-4` = 16px). */
export const ROW_GAP = 16

/**
 * Total height of one virtual row: card height + vertical gap.
 * Used for `estimateSize` in the virtualizer and must be kept in sync
 * with `CARD_HEIGHT` and `ROW_GAP`.
 */
export const ROW_HEIGHT_WITH_GAP = CARD_HEIGHT + ROW_GAP

/**
 * Pixel buffer for overscan — prevents blank flash during fast scroll.
 * Derived from ~5 rows at the default row height.
 */
export const OVERSCAN_PX = 800

/**
 * Cardinality breakpoint boundaries with descriptive names to avoid
 * confusion with Tailwind's `sm`/`md`/`lg`/`xl` naming.
 *
 * These values represent the **container width** (not viewport width)
 * that corresponds to each Tailwind viewport breakpoint, accounting for
 * the app layout's `max-w-*` constraints and padding.
 *
 * | Key        | Container | Viewport | Non-virt cols | Tailwind class  |
 * |------------|-----------|----------|---------------|-----------------|
 * | `tablet`   | 640px     | 768px    | 2 cols        | `md:grid-cols-2`|
 * | `desktop`  | 864px     | 1024px   | 2 cols        | `lg:grid-cols-2`|
 * | `wide`     | 992px     | 1280px   | 3 cols        | `xl:grid-cols-3`|
 *
 * Container width < viewport because the app's `<main>` is capped at
 * `max-w-lg`/`max-w-2xl`/`max-w-4xl`/`max-w-5xl` plus horizontal padding.
 * Using container-width breakpoints ensures the virtualized grid produces
 * the same column count as the Tailwind non-virtualized grid at every
 * viewport size.
 */
export const COL_BREAKPOINTS = {
  /** Container width at viewport `md` (768px) — switches to 2 columns. */
  tablet: 640,
  /** Container width at viewport `lg` (1024px) — still 2 columns. */
  desktop: 864,
  /** Container width at viewport `xl` (1280px) — switches to 3 columns. */
  wide: 992,
} as const

/**
 * Returns the number of grid columns to render for a given container width,
 * matching the Tailwind breakpoints used in the non-virtualized grid:
 *  `<640  → 1` (base)
 *  `<992  → 2` (md + lg)
 *  `≥992  → 3` (xl)
 *
 * The breakpoints are expressed in container-width pixels to account for
 * the app layout's `max-w-*` + padding constraints, ensuring the virtualized
 * and non-virtualized grids show the same number of columns at every
 * viewport size.
 *
 * Exported as a pure function for deterministic unit testing without a DOM.
 *
 * @param width - Container width in pixels. Non-finite or negative values
 *   return a safe default of 1.
 */
export function getColumnCount(width: number): number {
  if (!Number.isFinite(width) || width < 0) return 1
  if (width < COL_BREAKPOINTS.tablet) return 1 // base / mobile
  if (width < COL_BREAKPOINTS.wide) return 2 // tablet + desktop (both 2 cols)
  return 3 // wide
}

/**
 * Returns the subset of `threads` belonging to a given virtual row.
 *
 * In multi-column mode each virtual row contains up to `columnCount` threads,
 * starting at `rowIndex * columnCount`. The returned array may be shorter
 * than `columnCount` for the last (partial) row.
 *
 * @param threads - Full array of all threads.
 * @param rowIndex - Zero-based virtual row index.
 * @param columnCount - Number of columns in the grid (≥ 1).
 * @returns Slice of threads for this row, never exceeding `columnCount`.
 */
export function getRowThreads<T>(
  threads: T[],
  rowIndex: number,
  columnCount: number,
): T[] {
  const start = rowIndex * columnCount
  const end = Math.min(start + columnCount, threads.length)
  return threads.slice(start, end)
}
