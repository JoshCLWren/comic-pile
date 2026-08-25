import type { CSSProperties } from 'react'

/**
 * Desktop-first type scale for the Roll page Reading Context pillar (issue
 * #1873). Decision-relevant content must render at comfortably readable
 * sizes at a 1920px-class desktop viewport and 100% zoom instead of the
 * 8-10px cockpit microcopy this panel previously used.
 *
 * Sizes are expressed in CSS pixels and applied as inline font-size styles so
 * rendered regression tests can assert computed values rather than class
 * names. Colors stay on theme tokens via classes; only sizing lives here.
 */
export const READING_CONTEXT_TYPE = {
  /** Panel chrome label ("Reading Context"). */
  panelLabel: 12,
  /** Uppercase micro-label above a value ("Roll Result", "Blocked by:"). */
  statLabel: 11,
  /** Key numeric readout ("Rolled 7 on d20"). */
  statValue: 16,
  /** Section headings that carry primary information (series name). */
  sectionHeading: 14,
  /** Primary decision content: issue numbers, edge endpoints, route names. */
  primaryValue: 14,
  /** Interactive crossover chips. */
  chipLabel: 12,
  /** Explanatory sentences and dependency explanations. */
  bodyCopy: 13,
  /** Secondary metadata: star ratings, "starts at" positions, counts. */
  metaLabel: 12,
  /** Buttons inside the pillar ("Explain route", "Correct continuity"). */
  actionLabel: 12,
} as const

export type ReadingContextTypeRole = keyof typeof READING_CONTEXT_TYPE

/**
 * Readability floors each scale entry must meet. Tests fail if a future edit
 * shrinks any role below its floor or drops it from the scale entirely.
 */
export const READING_CONTEXT_TYPE_FLOORS = {
  panelLabel: 11,
  statLabel: 10,
  statValue: 14,
  sectionHeading: 13,
  primaryValue: 13,
  chipLabel: 12,
  bodyCopy: 12,
  metaLabel: 11,
  actionLabel: 11,
} as const satisfies Record<ReadingContextTypeRole, number>

/**
 * Builds the inline style for one typography role.
 *
 * Args:
 *   role: Semantic typography role within the Reading Context pillar.
 *
 * Returns:
 *   Inline CSS properties carrying the role's readable font size.
 */
export function readingContextType(role: ReadingContextTypeRole): CSSProperties {
  return { fontSize: `${READING_CONTEXT_TYPE[role]}px` }
}
