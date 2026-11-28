import type { CBLAdoptionPreview } from '../services/api-cbl-sources'

interface CblAdoptionSummaryProps {
  preview: CBLAdoptionPreview
  needsAttentionCount: number
}

/** Compact before/commit readout for one reviewed CBL source. */
export function CblAdoptionSummary({ preview, needsAttentionCount }: CblAdoptionSummaryProps) {
  const { summary } = preview
  return (
    <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
      <div>
        <dt className="text-[var(--theme-text-dim)]">
          {preview.total_positions === 1 ? 'Entry' : 'Entries'}
        </dt>
        <dd className="font-bold text-[var(--theme-text-primary)]">{preview.total_positions}</dd>
      </div>
      <div>
        <dt className="text-[var(--theme-text-dim)]">Already in ComicPile</dt>
        <dd className="font-bold text-[var(--theme-text-primary)]">{summary.reused_existing_count}</dd>
      </div>
      <div>
        <dt className="text-[var(--theme-text-dim)]">Will be added</dt>
        <dd className="font-bold text-[var(--theme-text-primary)]">{summary.missing_would_create_count}</dd>
      </div>
      <div>
        <dt className="text-[var(--theme-text-dim)]">Need attention</dt>
        <dd className="font-bold text-[var(--theme-text-primary)]">{needsAttentionCount}</dd>
      </div>
      <div>
        <dt className="text-[var(--theme-text-dim)]">Final list size</dt>
        <dd className="font-bold text-[var(--theme-text-primary)]">{summary.final_adopted_count}</dd>
      </div>
    </dl>
  )
}
