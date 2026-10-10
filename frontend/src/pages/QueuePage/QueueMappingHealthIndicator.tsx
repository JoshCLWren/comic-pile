interface QueueMappingHealthIndicatorProps {
  mapping: {
    status: 'fully_mapped' | 'partial' | 'unresolved' | 'needs_review' | 'not_applicable'
    tracked_issue_count: number
    confirmed_issue_count: number
    needs_mapping_count: number
    needs_review_count: number
  }
  onMapSeries?: () => void
}

export default function QueueMappingHealthIndicator({
  mapping,
  onMapSeries,
}: QueueMappingHealthIndicatorProps) {
  const { status, tracked_issue_count, confirmed_issue_count, needs_mapping_count, needs_review_count } = mapping

  if (status === 'fully_mapped' || status === 'not_applicable') {
    return null
  }

  const isReview = status === 'needs_review'
  const isPartial = status === 'partial'

  let label: string
  if (isReview) {
    label = needs_review_count > 0 ? `${needs_review_count} issue${needs_review_count === 1 ? '' : 's'} need review` : 'Review needed'
  } else if (isPartial) {
    label = `${confirmed_issue_count} of ${tracked_issue_count} mapped`
  } else {
    // unresolved
    label = needs_mapping_count > 0 ? `${needs_mapping_count} issue${needs_mapping_count === 1 ? '' : 's'} need mapping` : 'Mapping needed'
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider border-stone-400/30 bg-stone-800/50 text-stone-300" aria-label={label}>
      <span className="inline-flex items-center gap-1.5">
        {isReview ? (
          <>
            <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            <span>{label}</span>
          </>
        ) : (
          <>
            <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span>{label}</span>
          </>
        )}
      </span>
      {onMapSeries && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
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
