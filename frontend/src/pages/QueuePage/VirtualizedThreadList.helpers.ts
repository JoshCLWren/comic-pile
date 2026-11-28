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
 * Vertical distance (in px) from the top or bottom edge of the scroll
 * container within which a drag-over triggers auto-scrolling for
 * drag-to-reorder in the virtualized list.  Matches ~half a card height.
 */
export const EDGE_SCROLL_ZONE = 80


/**
 * Returns the subset of `threads` belonging to a given virtual row.
 *
 * In the single-column virtualization path, each virtual row contains
 * exactly one thread.
 *
 * @param threads - Full array of all threads.
 * @param rowIndex - Zero-based virtual row index.
 * @returns Array containing the thread at the given index, or empty if out of bounds.
 */
export function getRowThreads<T>(
  threads: T[],
  rowIndex: number,
): T[] {
  return rowIndex < threads.length ? [threads[rowIndex]] : []
}
