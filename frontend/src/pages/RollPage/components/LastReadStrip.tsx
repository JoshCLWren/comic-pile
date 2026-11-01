import { useEffect, useState } from 'react'
import type { RollLastReadView } from '../../../hooks/useRollLastRead'
import {
  rollSecondaryActionClass,
  rollUtilityActionClass,
} from '../actionClasses'

interface LastReadStripProps {
  view: RollLastReadView
  /** Local-only dismissal; session persistence is untouched. */
  onDismiss: () => void
  onRollAgain: () => void
  /** Reverses the rating behind this record. Owned by the page, not this strip. */
  onUndo?: () => void
  /** Pending state of the page-owned undo mutation. */
  undoPending?: boolean
  canUndo?: boolean
}

function issueLabel(view: RollLastReadView): string {
  const title = view.lastRead.thread_title?.trim() || 'Last read issue'
  const issueNumber = view.lastRead.issue_number?.trim()
  return issueNumber ? `${title} ${issueNumber}` : title
}

function ratingLabel(value: number): string {
  return Number.isInteger(value) ? `${value}/5` : `${value.toFixed(1)}/5`
}

/**
 * Idle Roll summary of the session's latest rate event (#2720).
 *
 * The strip renders only from data the rate mutation already returned and from
 * caches those surfaces populated: cover, identity, saved rating, canonical
 * series average/count, and thread progress. It issues no request of its own,
 * and dismissal is local UI state so a later rating replaces the record without
 * mutating persistence.
 */
export function LastReadStrip({
  view,
  onDismiss,
  onRollAgain,
  onUndo,
  undoPending = false,
  canUndo = false,
}: LastReadStripProps) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const [coverFailed, setCoverFailed] = useState(false)

  const recordKey = `${view.lastRead.issue_id ?? 'none'}:${view.lastRead.read_at ?? ''}`
  useEffect(() => {
    setCopyStatus('idle')
    setCoverFailed(false)
  }, [recordKey])

  const label = issueLabel(view)
  const title = view.lastRead.thread_title?.trim() || 'Last read issue'
  const issueNumber = view.lastRead.issue_number?.trim()
  const coverUrl = coverFailed ? null : view.coverUrl

  const seriesStats = view.seriesStats
  const seriesAverage = seriesStats?.averageRating ?? null
  const ratingCount = seriesStats?.ratingCount ?? 0
  const totalIssues = view.totalIssues ?? null
  const issuesRemaining = view.issuesRemaining ?? null
  const readCount =
    totalIssues != null && issuesRemaining != null && totalIssues > 0
      ? Math.max(totalIssues - issuesRemaining, 0)
      : null

  async function handleCopyComicReference() {
    try {
      await navigator.clipboard.writeText(label)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  return (
    <section
      aria-label="Last read"
      aria-live="polite"
      data-testid="last-read-strip"
      className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4 shadow-lg"
    >
      <div className="flex items-start gap-3">
        {coverUrl ? (
          <img
            src={coverUrl}
            alt={`${label} cover`}
            loading="lazy"
            onError={() => setCoverFailed(true)}
            className="h-20 w-14 shrink-0 rounded-lg border border-[var(--theme-border)] object-cover"
          />
        ) : (
          <div
            aria-label="Cover unavailable"
            className="flex h-20 w-14 shrink-0 items-center justify-center rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-lg font-black text-[var(--theme-text-dim)]"
          >
            {title.slice(0, 1).toUpperCase()}
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)]">
            Last read
          </p>
          <p className="truncate text-sm font-semibold text-[var(--theme-text-primary)]">
            {title}
            {issueNumber ? <span className="text-[var(--theme-text-muted)]"> {issueNumber}</span> : null}
          </p>

          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--theme-text-muted)]">
            {view.rating != null ? (
              <span className="font-semibold text-[var(--theme-personal-accent)]">
                Saved rating {ratingLabel(view.rating)}
              </span>
            ) : null}
            {seriesAverage != null && ratingCount > 0 ? (
              <span>
                Series average {seriesAverage.toFixed(1)}/5 · {ratingCount}{' '}
                {ratingCount === 1 ? 'rating' : 'ratings'}
              </span>
            ) : null}
            {readCount != null && totalIssues != null ? (
              <span>
                {readCount} of {totalIssues} issues read
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleCopyComicReference}
          className={`min-h-11 ${rollUtilityActionClass(copyStatus)}`}
          aria-label={`Copy ${label}`}
          aria-live="polite"
        >
          {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy title and issue'}
        </button>
        {canUndo && onUndo ? (
          <button
            type="button"
            onClick={onUndo}
            disabled={undoPending}
            className={`min-h-11 ${rollUtilityActionClass()}`}
            aria-label="Undo this rating"
          >
            {undoPending ? 'Undoing...' : 'Undo rating'}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onRollAgain}
          className={`min-h-11 ${rollSecondaryActionClass}`}
        >
          Roll again
        </button>
      </div>

      {copyStatus === 'failed' ? (
        <p className="mt-2 text-[10px] font-bold text-[var(--theme-danger)]" role="status">
          Copy failed. Use Retry copy to try again.
        </p>
      ) : null}

      <button
        type="button"
        onClick={onDismiss}
        className="mt-3 rounded-lg px-2 py-1.5 text-xs font-medium text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-label="Dismiss last read"
      >
        Dismiss
      </button>
    </section>
  )
}
