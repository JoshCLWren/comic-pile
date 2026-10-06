import type { ThreadListItem } from '../types'
import { getQueueMappingHealth } from '../types/queue-mapping'

interface QueueMappingHealthIndicatorProps {
  /** Queue row from the existing paginated Queue response. */
  thread: ThreadListItem
  /** Opens the shared Map series repair flow for this exact thread. */
  onMapSeries: () => void
}

function pluralize(count: number, singular: string, plural: string): string {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`
}

/**
 * Compact ComicVine mapping-health indicator for a Queue row (issue #2773).
 *
 * Reads the persisted #2776 projection already on the Queue response and never
 * fetches issue identity or calls ComicVine to render. Fully mapped series and
 * rows without an applicable projection render nothing. Ordinary missing
 * mappings read as a quiet count while ambiguous/conflicting identities are
 * explicitly labeled as needing review rather than presented as ordinary
 * missing mappings. Status is carried by text, never by color alone.
 *
 * The row stays a single wrapping line so card height, virtualization, and
 * pagination behavior are unaffected.
 */
export default function QueueMappingHealthIndicator({
  thread,
  onMapSeries,
}: QueueMappingHealthIndicatorProps) {
  const health = getQueueMappingHealth(thread)
  if (health === null) return null
  if (health.status === 'not_applicable' || health.status === 'fully_mapped') return null

  const needsReview = health.status === 'needs_review' || health.needs_review_count > 0
  const parts: string[] = []
  if (health.needs_mapping_count > 0) {
    parts.push(pluralize(health.needs_mapping_count, 'issue needs mapping', 'issues need mapping'))
  }
  if (health.needs_review_count > 0) {
    parts.push(
      pluralize(health.needs_review_count, 'issue needs review', 'issues need review'),
    )
  }
  // A review-needed row whose counts both read zero still needs a truthful
  // label rather than silence: the stored state says human review is required.
  if (parts.length === 0) {
    parts.push(needsReview ? 'needs review' : 'needs mapping')
  }
  const statusText = needsReview ? `Needs review: ${parts.join(' · ')}` : parts.join(' · ')

  return (
    <div
      data-testid="queue-mapping-health"
      className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1"
    >
      <span
        role="status"
        aria-label={`ComicVine mapping status for ${thread.title}: ${statusText}`}
        className={
          needsReview
            ? 'text-xs font-semibold text-[var(--theme-warning)]'
            : 'text-xs font-medium text-[var(--theme-text-dim)]'
        }
      >
        {statusText}
      </span>
      <button
        type="button"
        onClick={onMapSeries}
        data-testid="queue-mapping-map-series"
        aria-label={`Map ${thread.title} series on ComicVine`}
        className="rounded-lg border border-[var(--theme-border)] px-2 py-0.5 text-[11px] font-bold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
      >
        Map series
      </button>
    </div>
  )
}
