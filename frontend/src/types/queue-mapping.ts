import type { ThreadListItem } from './index'
import { isNumber, isObject, isString } from '../utils/runtimeChecks'

/**
 * Closed ComicVine mapping-health vocabulary for a Queue row (issue #2776).
 *
 * Mirrors the backend `ComicVineMappingStatus`: `not_applicable` threads do not
 * use issue tracking, `fully_mapped` threads stay quiet, `partial` and
 * `unresolved` threads have ordinary missing mappings, and `needs_review`
 * threads have ambiguous/conflicting identities that need human review.
 */
export type QueueMappingHealthStatus =
  | 'not_applicable'
  | 'fully_mapped'
  | 'partial'
  | 'unresolved'
  | 'needs_review'

/**
 * Compact persisted mapping-health projection scoped to one Queue thread.
 *
 * Derived from stored canonical issue mappings only. Counts describe the
 * issues represented by the Queue thread; they are a health indicator, not
 * provider-series scope proof for bulk mapping.
 */
export interface QueueComicVineMappingHealth {
  status: QueueMappingHealthStatus
  tracked_issue_count: number
  confirmed_issue_count: number
  needs_mapping_count: number
  needs_review_count: number
}

/**
 * Queue row shape once the regenerated OpenAPI artifact carries the #2776
 * projection. The checked-in `QueueThreadListItem` transport type predates that
 * field, so this intersection is the narrow frontend-owned bridge until
 * `python scripts/generate_openapi_types.py` is re-run (no Python runtime in
 * this worker; CI owns regeneration). Runtime Queue responses already carry
 * `comicvine_mapping`; nothing here invents status from titles.
 */
export type QueueThreadWithMappingHealth = ThreadListItem & {
  comicvine_mapping?: QueueComicVineMappingHealth | null
}

const KNOWN_STATUSES: ReadonlySet<string> = new Set([
  'not_applicable',
  'fully_mapped',
  'partial',
  'unresolved',
  'needs_review',
])

function isMappingHealth(value: unknown): value is QueueComicVineMappingHealth {
  if (!isObject(value)) return false
  const status = value['status']
  return (
    isString(status)
    && KNOWN_STATUSES.has(status)
    && isNumber(value['tracked_issue_count'])
    && isNumber(value['confirmed_issue_count'])
    && isNumber(value['needs_mapping_count'])
    && isNumber(value['needs_review_count'])
  )
}

/**
 * Read the persisted ComicVine mapping-health projection for a Queue row.
 *
 * Returns `null` when the projection is absent or not applicable, so callers
 * stay quiet instead of fetching issue identity per card (issue #2773 forbids
 * per-card identity and live provider requests while rendering the Queue).
 *
 * @param thread - Queue row from the existing paginated Queue response.
 * @returns The stored mapping health, or `null` when there is nothing to show.
 */
export function getQueueMappingHealth(thread: ThreadListItem): QueueComicVineMappingHealth | null {
  // SAFETY: The runtime Queue response carries the `comicvine_mapping` field
  const candidate = (thread as QueueThreadWithMappingHealth).comicvine_mapping
  if (candidate == null) return null
  return isMappingHealth(candidate) ? candidate : null
}
