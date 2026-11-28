/**
 * Reader-facing History filter state for `GET /api/v2/activity`.
 *
 * The page owns editable draft strings; these helpers produce the canonical
 * values used in both the HTTP query and the React Query key so different
 * spellings of the same filter never split the cache.
 */

export type ActivityFilters = {
  /** Literal text search over series, issue number and action type. */
  q: string
  /** Literal series-title filter. */
  series: string
  /** Reader-visible activity type. */
  type: string
  /** Inclusive reader-local start date, `YYYY-MM-DD`. */
  dateFrom: string
  /** Inclusive reader-local end date, `YYYY-MM-DD`. */
  dateTo: string
}

export const EMPTY_ACTIVITY_FILTERS: ActivityFilters = {
  q: '',
  series: '',
  type: '',
  dateFrom: '',
  dateTo: '',
}

/**
 * Normalize filter strings before they reach a query key or the server.
 *
 * @param filters - Editable filter state, or `undefined` for the unfiltered stream.
 * @returns Trimmed values with a lower-cased activity type.
 */
export function normalizeActivityFilters(filters?: ActivityFilters): ActivityFilters {
  if (!filters) return { ...EMPTY_ACTIVITY_FILTERS }
  return {
    q: filters.q.trim(),
    series: filters.series.trim(),
    type: filters.type.trim().toLowerCase(),
    dateFrom: filters.dateFrom.trim(),
    dateTo: filters.dateTo.trim(),
  }
}

/**
 * Whether any filter is currently narrowing the activity stream.
 *
 * @param filters - Filter state to inspect.
 * @returns True when at least one filter has a non-blank value.
 */
export function hasActiveActivityFilters(filters: ActivityFilters): boolean {
  const normalized = normalizeActivityFilters(filters)
  return (
    normalized.q !== '' ||
    normalized.series !== '' ||
    normalized.type !== '' ||
    normalized.dateFrom !== '' ||
    normalized.dateTo !== ''
  )
}
