import { useEffect, useState, type CSSProperties } from 'react'
import Modal from '../../../components/Modal'
import Tooltip from '../../../components/Tooltip'
import GlossaryLink from '../../../components/GlossaryLink'
import { RATING_THRESHOLD, getDieDirection } from '../utils'
import type { RatingThread } from '../types'

interface DecisionCardProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rating: number
  predictedDie: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending?: boolean
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
  onCancel: () => void
}

export function DecisionCard({
  activeRatingThread,
  currentDie,
  rating,
  predictedDie,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  skipIsPending = false,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onSkip,
  onCancel,
}: DecisionCardProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const isLastIssue = issuesRemaining === 1
  const threadTitle = activeRatingThread?.title ?? null
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const dieDirection = getDieDirection(currentDie, predictedDie)
  const ratingFillPct = Math.min(
    100,
    Math.max(0, ((rating - 0.5) / (5.0 - 0.5)) * 100),
  )

  const [isSkipConfirmOpen, setIsSkipConfirmOpen] = useState(false)
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    setCopyStatus('idle')
  }, [threadTitle, issueNumber])

  const handleConfirmSkip = () => {
    setIsSkipConfirmOpen(false)
    onSkip?.()
  }

  async function handleCopyComicReference() {
    if (!threadTitle || issueNumber == null) return

    try {
      await navigator.clipboard.writeText(`${threadTitle} ${issueNumber}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  return (
    <section
      aria-labelledby="decision-heading"
      className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 md:p-4"
      data-testid="decision-card"
    >
      <div className="flex items-center justify-between gap-2 border-b border-[var(--theme-border)] pb-2">
        <h3 id="decision-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          Your rating
        </h3>
        {threadTitle && issueNumber != null && (
          <button
            type="button"
            onClick={handleCopyComicReference}
            disabled={!threadTitle}
            className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-2.5 text-[10px] font-black uppercase tracking-wider transition focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-40 shrink-0 ${copyStatus === 'copied' ? 'border-[var(--theme-continuity-accent)]/40 bg-[var(--theme-continuity-accent)]/15 text-[var(--theme-continuity-accent)]' : copyStatus === 'failed' ? 'border-[var(--theme-danger)]/30 bg-[var(--theme-danger)]/10 text-[var(--theme-danger)]' : 'border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'}`}
            aria-label={`Copy ${threadTitle} ${issueNumber}`}
            data-testid="copy-title-button"
          >
            <svg
              className="h-3.5 w-3.5 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H11a3 3 0 0 1 3 3v17a3 3 0 0 0-3-3H6.5A2.5 2.5 0 0 0 4 21.5v-17Z"></path>
              <path d="M20 4.5A2.5 2.5 0 0 0 17.5 2H14"></path>
              <path d="M20 4.5v17A2.5 2.5 0 0 0 17.5 19H14"></path>
            </svg>
            {copyStatus === 'copied' ? 'COPIED' : copyStatus === 'failed' ? 'Retry' : 'Copy title'}
          </button>
        )}
      </div>

      {copyStatus === 'failed' ? (
        <p role="status" className="text-[10px] font-bold text-rose-400">
          Copy failed. Use Retry to try again.
        </p>
      ) : null}

      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the series to the front of the queue and step the die down. Lower ratings move it past the next roll range and step the die up.`}>
            <p id="rating-value" className={`text-5xl font-black ${rating >= RATING_THRESHOLD ? 'text-[var(--theme-personal-accent)]' : 'text-[var(--theme-danger)]'}`}>
              {rating.toFixed(1)}
            </p>
          </Tooltip>
          <p className="text-[11px] font-bold text-stone-400">
            <GlossaryLink id="die-ladder">d{currentDie} → d{predictedDie}</GlossaryLink>
          </p>
        </div>
        <p className="text-[10px] font-bold text-stone-500 shrink-0">{dieDirection}</p>
      </div>

      <input
        type="range"
        id="rating-input"
        name="rating"
        min="0.5"
        max="5.0"
        step="0.5"
        value={rating}
        className="rating-slider h-4 w-full"
        style={{ '--slider-fill': `${ratingFillPct}%` } as CSSProperties}
        aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
        aria-describedby="rating-value queue-effect"
        onChange={(event) => onUpdateRating(event.target.value)}
      />

      <p id="queue-effect" className="text-[11px] font-bold leading-relaxed text-stone-400">
        {rating >= RATING_THRESHOLD
          ? 'Moves this series to the front of the queue.'
          : 'Moves this series beyond the next roll range.'}
      </p>

      {isLastIssue && (
        <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
            This is the last issue in the series
          </p>
        </div>
      )}

      {errorMessage ? (
        <div id="error-message" className="text-center text-[10px] font-bold text-rose-500" role="alert">
          {errorMessage}
        </div>
      ) : null}

      <div
        className="sticky bottom-0 -mx-3 md:static md:mx-0 space-y-2 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] md:pt-1 md:pb-0 border-t border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 md:px-0 backdrop-blur"
        data-testid="rating-actions"
      >
        <button
          type="button"
          onClick={() => onSubmitRating(false)}
          disabled={rateIsPending}
          data-testid="save-and-continue"
          className="w-full rounded-xl border border-[var(--theme-comic-accent)]/50 bg-[var(--theme-comic-accent)]/25 py-3.5 text-xs font-black uppercase tracking-[0.15em] transition hover:bg-[var(--theme-comic-accent)]/35 focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50 active:scale-[0.98]"
        >
          {rateIsPending ? 'Saving…' : isLastIssue ? 'Mark read & complete' : 'Mark read & save'}
        </button>

        <div className="flex gap-2" data-testid="rating-secondary-actions">
          <button
            type="button"
            onClick={onSnooze}
            disabled={snoozeIsPending}
            className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
          >
            {snoozeIsPending ? 'Snoozing…' : 'Snooze'}
          </button>
          {onSkip && (
            <button
              type="button"
              onClick={() => setIsSkipConfirmOpen(true)}
              disabled={skipIsPending}
              data-testid="skip-roll"
              aria-label="Skip current roll"
              className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
            >
              {skipIsPending ? 'Skipping…' : 'Skip'}
            </button>
          )}
          <button
            type="button"
            onClick={onCancel}
            disabled={dismissIsPending}
            className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-transparent py-3 text-xs font-black uppercase tracking-[0.15em] text-[var(--theme-text-muted)] transition hover:bg-white/10 hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
          >
            Cancel roll
          </button>
        </div>
      </div>

      <Modal
        isOpen={isSkipConfirmOpen}
        title="Skip comic"
        onClose={() => setIsSkipConfirmOpen(false)}
        data-testid="skip-confirm-dialog"
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Skip moves past this rolled comic without saving a rating. Nothing is marked read, and
            it can come up again in a future roll.
          </p>
          <p className="text-xs text-[var(--theme-text-dim)]">
            Snooze postpones the comic temporarily, and Cancel roll exits without rating. Skip is
            different from both — it moves past this comic now.
          </p>
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              type="button"
              onClick={() => setIsSkipConfirmOpen(false)}
              disabled={skipIsPending}
              data-testid="skip-cancel"
              className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-50"
            >
              Keep this comic
            </button>
            <button
              type="button"
              onClick={handleConfirmSkip}
              disabled={skipIsPending}
              data-testid="skip-confirm"
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
            >
              {skipIsPending ? 'Skipping…' : 'Skip comic'}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  )
}