import type { ReadingGraphPreview } from '../services/api-reading-graph'
import {
  effectiveOverlapChoice,
  overlapDecisionLabel,
  readingGraphSeriesLabel,
  readingGraphSeriesStatus,
  readingGraphSummaryLine,
  readingGraphWaitLabels,
  unresolvedOverlaps,
  type ReadingGraphChoices,
} from '../utils/readingGraphOverlaps'

interface ReadingGraphSummaryProps {
  /** Server-provided prospective graph for the current selection. */
  preview: ReadingGraphPreview
  /** Answers made during this preview session. */
  choices: ReadingGraphChoices
  /** Open the series-by-series questionnaire. */
  onReview: () => void
  /** Disable interaction while a commit is in flight. */
  disabled?: boolean
}

/**
 * Compact reading-graph panel shown beside the CBL selection.
 *
 * It names which series can continue and which ones wait, plus the reader's
 * current per-volume decisions. The panel is only rendered when the server
 * reports at least one genuine overlap; a source without a real conflict keeps
 * the one-decision flow and never shows a questionnaire.
 *
 * @param props - Graph preview, current answers, and the review action.
 * @returns The inline reading-graph summary.
 */
export default function ReadingGraphSummary({
  preview,
  choices,
  onReview,
  disabled = false,
}: ReadingGraphSummaryProps) {
  const pending = unresolvedOverlaps(preview, choices)
  const decisionCount = preview.overlaps.length
  const reviewLabel =
    pending.length > 0
      ? `Resolve ${pending.length} ${pending.length === 1 ? 'series overlap' : 'series overlaps'}`
      : 'Review series decisions'

  return (
    <section
      className="space-y-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
      aria-labelledby="reading-graph-heading"
      data-testid="reading-graph-summary"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3
          id="reading-graph-heading"
          className="text-sm font-bold text-[var(--theme-text-primary)]"
        >
          Reading graph
        </h3>
        <p className="text-xs text-[var(--theme-text-muted)]">{readingGraphSummaryLine(preview)}</p>
      </div>

      {preview.cycle_errors.length > 0 && (
        <div role="alert" className="text-sm text-[var(--theme-danger)]">
          <p className="font-bold">This reading order cannot be saved yet.</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
            {preview.cycle_errors.map((error) => (
              <li key={error.code}>{error.message}</li>
            ))}
          </ul>
        </div>
      )}

      <ul className="space-y-2" aria-label="Series in this reading graph">
        {preview.series.map((node) => {
          const waitsFor = readingGraphWaitLabels(preview, node)
          return (
            <li
              key={node.comicvine_volume_id}
              className="rounded-lg border border-[var(--theme-border)] px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-bold text-[var(--theme-text-primary)]">
                  {readingGraphSeriesLabel(node)}
                </span>
                <span
                  className={`text-xs font-bold ${
                    node.state === 'continues'
                      ? 'text-emerald-300'
                      : node.state === 'waits'
                        ? 'text-amber-200'
                        : 'text-[var(--theme-text-muted)]'
                  }`}
                >
                  {readingGraphSeriesStatus(node)}
                </span>
              </div>
              <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
                {node.rollable_count} rollable · {node.waiting_count} waiting ·{' '}
                {node.unread_count} unread
              </p>
              {waitsFor.length > 0 && (
                <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
                  Waits for {waitsFor.slice(0, 4).join(', ')}
                  {waitsFor.length > 4 ? ` and ${waitsFor.length - 4} more` : ''}
                </p>
              )}
            </li>
          )
        })}
      </ul>

      {decisionCount > 0 && (
        <div className="space-y-2 border-t border-[var(--theme-border)] pt-3">
          <h4 className="text-xs font-bold text-[var(--theme-text-primary)]">
            {decisionCount === 1 ? 'Series decision' : 'Series decisions'}
          </h4>
          <ul className="space-y-1">
            {preview.overlaps.map((overlap) => {
              const decided = effectiveOverlapChoice(overlap, choices) !== null
              return (
                <li key={overlap.overlap_id} className="text-xs text-[var(--theme-text-muted)]">
                  <span className="font-bold text-[var(--theme-text-primary)]">
                    {readingGraphSeriesLabel(overlap.waiting_series)}
                  </span>{' '}
                  {decided ? (
                    <span>{overlapDecisionLabel(overlap, choices)}</span>
                  ) : (
                    <span className="text-amber-200">Needs a decision before saving</span>
                  )}
                </li>
              )
            })}
          </ul>
          <button
            type="button"
            onClick={onReview}
            disabled={disabled}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
          >
            {reviewLabel}
          </button>
        </div>
      )}
    </section>
  )
}
