import type { components } from '../../generated/openapi'

type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']

interface QueueMappingHealthIndicatorProps {
  mapping: ComicVineMappingHealth
  onMapSeries?: () => void
}

/**
 * Compact ComicVine mapping-health badge for a Queue series card (issue #2773).
 *
 * Fully mapped or non-issue-tracked series render nothing, so healthy rows stay
 * quiet. Unresolved rows say how many issues need mapping; rows with ambiguous or
 * conflicting identities say review is required instead of being presented as
 * ordinary missing mappings. Status is conveyed by text, not color alone.
 */
export default function QueueMappingHealthIndicator({
  mapping,
  onMapSeries,
}: QueueMappingHealthIndicatorProps) {
  const { status, tracked_issue_count, confirmed_issue_count, needs_mapping_count, needs_review_count } =
    mapping
  const metadataMissing = mapping.metadata_missing_count ?? 0

  if ((status === 'fully_mapped' && metadataMissing === 0) || status === 'not_applicable') {
    return null
  }

  const isReview = status === 'needs_review'
  const isPartial = status === 'partial'

  let label: string
  if (isReview) {
    label =
      needs_review_count > 0
        ? needs_review_count === 1
          ? '1 issue needs review'
          : `${needs_review_count} issues need review`
        : 'Review needed'
  } else if (metadataMissing > 0) {
    label = `${metadataMissing} ${metadataMissing === 1 ? 'issue is' : 'issues are'} missing details`
  } else if (isPartial) {
    label = `${confirmed_issue_count} of ${tracked_issue_count} mapped`
  } else {
    // unresolved
    label =
      needs_mapping_count > 0
        ? needs_mapping_count === 1
          ? '1 issue needs mapping'
          : `${needs_mapping_count} issues need mapping`
        : 'Mapping needed'
  }

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider border-stone-400/30 bg-stone-800/50 text-stone-300"
      aria-label={label}
      data-testid="queue-mapping-health-indicator"
    >
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className={`w-1.5 h-1.5 rounded-full ${isReview ? 'bg-[var(--theme-danger)]' : 'bg-[var(--theme-warning)]'}`}
        />
        <span>{label}</span>
      </span>
      {onMapSeries && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onMapSeries()
          }}
          className="underline underline-offset-2 hover:text-[var(--theme-text-primary)] transition-colors"
          aria-label="Map series"
          data-testid="queue-map-series-btn"
        >
          Map series
        </button>
      )}
    </span>
  )
}
