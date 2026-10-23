import { Link } from 'react-router-dom'
import type { CBLSourceComparisonMatch } from '../services/api-cbl-sources'
import { displayCblSourceTitle } from '../utils/cblSourceDisplay'

interface CblComparisonListProps {
  /** Ranked source comparisons, best match first. */
  candidates: CBLSourceComparisonMatch[]
  /** Distinct input comics the comparison was run against. */
  inputTotal: number
  /** Message shown when there are no candidate sources. */
  emptyMessage: string
  /** Router location to return to when a reader opens a source detail. */
  backTo?: string
  /** Human label for the originating surface, echoed on the source page. */
  backLabel?: string
  /** Stable test id prefix so both flows can be asserted independently. */
  testIdPrefix: string
}

/**
 * Describe the relative-order verdict for one compared source.
 *
 * @param candidate - One ranked source comparison.
 * @returns A short reader-facing order summary.
 */
function orderSummary(candidate: CBLSourceComparisonMatch): string {
  if (candidate.order_status === 'same_order') return 'Same relative order'
  if (candidate.order_status === 'reordered') {
    return `Reordered: ${candidate.order_disagreement_count} of ${candidate.order_pair_count} comic pairs differ`
  }
  return 'Order not comparable'
}

/**
 * Render ranked shared CBL sources with coverage, duplicate, and order evidence.
 *
 * Coverage counts distinct exact Comic Vine identities, so a duplicated source
 * position is reported as a note and never inflates the matched comic count.
 * Same-titled volumes never appear because matching is by exact ID only.
 */
export function CblComparisonList({
  candidates,
  inputTotal,
  emptyMessage,
  backTo,
  backLabel,
  testIdPrefix,
}: CblComparisonListProps) {
  if (candidates.length === 0) {
    return <p className="text-sm text-[var(--theme-text-muted)]">{emptyMessage}</p>
  }
  return (
    <ol className="space-y-2">
      {candidates.map((candidate) => {
        const redundantPositions =
          candidate.matched_occurrence_count - candidate.matched_input_count
        const title =
          displayCblSourceTitle(candidate.list_name, candidate.source_path) ??
          candidate.list_name
        return (
          <li
            key={candidate.list_id}
            data-testid={`${testIdPrefix}-${candidate.list_id}`}
            className="surface-panel space-y-2 rounded-xl p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <h5 className="text-sm font-bold text-[var(--theme-text-primary)]">{title}</h5>
              <span className="shrink-0 text-xs font-semibold text-[var(--theme-continuity-accent)]">
                Score {candidate.score} of 100
              </span>
            </div>
            <ul className="space-y-1 text-xs text-[var(--theme-text-muted)]">
              <li>
                Coverage: {candidate.matched_input_count} of {inputTotal} comics (
                {candidate.input_coverage_percentage}%)
              </li>
              <li>
                Source coverage: {candidate.source_coverage_percentage}% of this source&apos;s{' '}
                {candidate.distinct_source_issues} comics
              </li>
              <li data-testid={`${testIdPrefix}-order-${candidate.list_id}`}>
                {orderSummary(candidate)}
              </li>
              {redundantPositions > 0 && (
                <li data-testid={`${testIdPrefix}-duplicate-${candidate.list_id}`}>
                  {redundantPositions} duplicate source{' '}
                  {redundantPositions === 1 ? 'position counts' : 'positions count'} once
                </li>
              )}
              {candidate.source_only_issue_count > 0 && (
                <li>
                  {candidate.source_only_issue_count} source{' '}
                  {candidate.source_only_issue_count === 1 ? 'comic is' : 'comics are'} not in this
                  list
                </li>
              )}
            </ul>
            <Link
              to={`/cbl-sources?list=${candidate.list_id}`}
              state={{ from: backTo, label: backLabel }}
              className="inline-flex min-h-9 items-center text-xs font-bold text-[var(--theme-continuity-accent)] hover:text-[var(--theme-text-primary)]"
            >
              View source list: {title}
            </Link>
          </li>
        )
      })}
    </ol>
  )
}

export default CblComparisonList
