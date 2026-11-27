/**
 * Pure geometry for the Night Shift Roll presentation (issue #5981).
 *
 * The approved HTML reference sizes covers from the measured board width, the
 * available viewport height and the die size. Keeping that arithmetic here (and
 * out of the component) makes the cover-first board testable without a browser
 * and guarantees every supported die gets one stable, centered arrangement.
 *
 * These values describe presentation only. The authoritative face-to-issue
 * mapping and pool order still come from the Roll resources; nothing here
 * invents, reorders or backfills a face.
 */

/** Dice sizes the production Roll engine supports. Do not add prototype sizes. */
export const PRODUCTION_DICE_SIDES = [2, 4, 6, 8, 10, 12, 20] as const

export type ProductionDie = (typeof PRODUCTION_DICE_SIDES)[number]

/** `[top row, middle row, bottom row]`; the die always sits in the middle row. */
export type CoverArrangement = readonly [number, number, number]

const ARRANGEMENTS: Record<ProductionDie, CoverArrangement> = {
  2: [0, 2, 0],
  4: [2, 0, 2],
  6: [2, 2, 2],
  8: [3, 2, 3],
  10: [4, 2, 4],
  12: [4, 4, 4],
  20: [7, 6, 7],
}

/** Widest cover row for each die; used to keep covers inside the board. */
const MAX_COLUMNS: Record<ProductionDie, number> = {
  2: 2,
  4: 2,
  6: 3,
  8: 3,
  10: 4,
  12: 4,
  20: 7,
}

/** Minimum legible cover width. Prototype art is never enlarged past its box. */
export const MIN_COVER_WIDTH = 34

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/**
 * Coerce any caller-supplied die value to a supported production size. An
 * unknown size falls back to d6, matching the scoped die-state fallback.
 */
export function resolveProductionDie(value: number): ProductionDie {
  return (PRODUCTION_DICE_SIDES as readonly number[]).includes(value)
    ? (value as ProductionDie)
    : 6
}

export function getCoverArrangement(value: number): CoverArrangement {
  return ARRANGEMENTS[resolveProductionDie(value)]
}

export interface CoverBoardLayout {
  arrangement: CoverArrangement
  /** Gap between covers and between the die and its neighboring covers. */
  gap: number
  /** Natural-proportion (2:3) cover width in CSS pixels. */
  coverWidth: number
  /** Square die width in CSS pixels. */
  dieWidth: number
}

interface CoverBoardLayoutParams {
  /** Measured content width of the board. */
  width: number
  /** Viewport height, used only as a soft ceiling for cover size. */
  viewportHeight: number
  dieSize: number
}

/**
 * Compute the centered cover-first board geometry.
 *
 * Covers are capped by both the widest row and the middle row (which shares
 * its width with the die), then by a viewport-height ceiling so a d20 board
 * never turns into a page of scrolling thumbnails. All values are finite and
 * positive, including zero/negative measurements during layout transitions.
 */
export function computeCoverBoardLayout({
  width,
  viewportHeight,
  dieSize,
}: CoverBoardLayoutParams): CoverBoardLayout {
  const sides = resolveProductionDie(dieSize)
  const arrangement = ARRANGEMENTS[sides]
  const usableWidth = Math.max(0, width)
  const gap = usableWidth < 500 ? 8 : 13
  const maxColumns = MAX_COLUMNS[sides]
  const dieWidth = clamp(Math.round(usableWidth * 0.17), 62, 165)

  const fitTopRow = Math.max(0, usableWidth - (maxColumns - 1) * gap) / maxColumns
  const middleCount = arrangement[1]
  const fitMiddleRow =
    middleCount > 0
      ? Math.max(0, usableWidth - dieWidth - (middleCount + 1) * gap) / middleCount
      : fitTopRow

  const maxHeight = Math.max(450, Math.min(1000, viewportHeight * 0.79))
  const middleRowCount = middleCount > 0 ? 3 : 2
  const heightFit = (maxHeight - 2 * gap) / (middleRowCount * 1.5)

  const coverWidth = Math.floor(
    Math.max(
      MIN_COVER_WIDTH,
      sides === 2
        ? Math.min(fitMiddleRow, maxHeight / 1.5)
        : Math.min(fitTopRow, fitMiddleRow, heightFit),
    ),
  )

  return { arrangement, gap, coverWidth, dieWidth }
}

/** Wrap a carousel index into `[0, length)`, including negative deltas. */
export function wrapCarouselIndex(index: number, length: number): number {
  if (length <= 0) return 0
  return ((index % length) + length) % length
}

/**
 * Shortest wraparound distance from the active cover to `index`. The gallery
 * keeps only the active cover and its two neighbors visible, so a d20 gallery
 * can step from face 20 to face 1 in one move.
 */
export function carouselOffset(index: number, active: number, length: number): number {
  if (length <= 0) return 0
  let distance = index - wrapCarouselIndex(active, length)
  const half = length / 2
  if (distance > half) distance -= length
  if (distance < -half) distance += length
  return distance
}

/** CSS transform for one cover in the wraparound gallery. */
export function carouselTransform(offset: number, coverWidth: number): string {
  const step = coverWidth * 0.89 + 16
  return `translateX(calc(-50% + ${offset * step}px)) scale(${offset === 0 ? 1 : 0.84})`
}

/** Mobile dominant-cover width, matching the reference's clamp. */
export function galleryCoverWidth(width: number): number {
  return clamp(Math.round(width * 0.65), 140, 250)
}

/** Pointer travel that counts as a swipe rather than a tap on a cover. */
export const GALLERY_SWIPE_THRESHOLD = 35
