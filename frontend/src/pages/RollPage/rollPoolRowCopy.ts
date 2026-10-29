import type {
  RollPoolIdentityState,
  RollPoolRow,
} from '../../types/rollBootstrap'

/**
 * Compact status copy for an identity state that is not quietly confirmed.
 *
 * The series-mapping UI does not exist yet, so unresolved/ambiguous rows get a
 * status badge only and never a dead "Map series" control.
 */
const IDENTITY_STATUS_COPY: Record<Exclude<RollPoolIdentityState, 'confirmed'>, string> = {
  candidate: 'Identity candidate',
  unresolved: 'Identity unresolved',
  ambiguous: 'Identity ambiguous',
  conflicting: 'Identity conflict',
}

/**
 * Format a rating value without inventing precision.
 *
 * @param value - Rating on the 0–5 scale.
 * @returns Whole ratings without decimals, otherwise one decimal place.
 */
export function formatRatingValue(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)
}

/**
 * Truthful progress copy for one pool row.
 *
 * A canonical run uses the full stored provider/catalog issue count as its
 * denominator. A thread-scoped fallback is labelled as thread progress so it
 * can never read like full-series run progress. When the denominator is null
 * no denominator or percentage is invented.
 *
 * @param row - The pool row to describe.
 * @returns The progress sentence, or null when no progress data exists.
 */
export function rollProgressCopy(row: RollPoolRow): string | null {
  const readCount = row.read_count ?? null
  const issueCount = row.issue_count ?? null
  if (readCount === null && issueCount === null) return null

  let detail: string
  if (readCount === null) {
    detail = `${issueCount} issues`
  } else if (issueCount === null) {
    detail = `${readCount} read`
  } else {
    detail = `${readCount} of ${issueCount} read`
  }

  return row.progress_scope === 'thread' ? `Thread progress · ${detail}` : detail
}

/**
 * Canonical-series rating context for one pool row.
 *
 * Latest and average render only from stored rating history; a row with no
 * rating history renders no rating line at all.
 *
 * @param row - The pool row to describe.
 * @returns The rating sentence, or null when no rating history exists.
 */
export function rollRatingCopy(row: RollPoolRow): string | null {
  const parts: string[] = []
  if (row.latest_rating != null) {
    parts.push(`Latest ${formatRatingValue(row.latest_rating)}`)
  }
  if (row.average_rating != null) {
    const average = `Avg ${formatRatingValue(row.average_rating)}`
    parts.push(
      row.rating_count != null ? `${average} from ${row.rating_count}` : average,
    )
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

/**
 * Bounded group names for one pool row. `kind` is frozen to `group`, so the
 * names are rendered neutrally and never inferred as crossover vs plan.
 *
 * @param row - The pool row to describe.
 * @returns Non-empty group names, in server order.
 */
export function rollGroupNames(row: RollPoolRow): string[] {
  const names = row.routes?.map((route) => route.name) ?? row.route_labels ?? []
  return names.filter((name) => name.trim().length > 0)
}

/**
 * Status badge copy for a non-confirmed identity state.
 *
 * @param state - Frozen identity state from the v2 bootstrap.
 * @returns Badge copy, or null for a confirmed/absent state.
 */
export function rollIdentityStatusCopy(
  state: RollPoolIdentityState | null | undefined,
): string | null {
  if (!state || state === 'confirmed') return null
  return IDENTITY_STATUS_COPY[state]
}
