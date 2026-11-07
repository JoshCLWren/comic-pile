import { useEffect, useState } from 'react'
import GlossaryLink from '../../../components/GlossaryLink'
import { ComicIssueRatingSlider } from '../../../components/ComicIssueCard'
import { RATING_THRESHOLD, getRatingColorClass } from '../utils'
import {
  rollPrimaryActionClass,
  rollSecondaryActionClass,
  rollSecondaryActionGroupClass,
  rollUtilityActionClass,
} from '../actionClasses'
import type { RatingThread } from '../types'

interface DecisionCardProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rating: number
  predictedDie: number
  errorMessage: string
  rateIsPending: boolean
  rerollIsPending?: boolean
  dismissIsPending: boolean
  manualDie: number | null
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onReroll?: () => Promise<void>
  onResetDice?: () => void
  onCancel: () => void
}

/**
 * DecisionCard component displays the rating interface after a user rolls a comic.
 *
 * Key features:
 * - Rating slider with visual feedback based on rating value
 * - Die readout that reports the truthful die outcome for the active mode
 * - Action buttons for saving, rolling again, and canceling
 *
 * Manual die mode:
 * - When `manualDie` is not null the die is pinned, so the ladder move never
 *   happens and the card says so instead of promising one (#3144). The wording
 *   matches the die-mode copy the die selector already uses.
 * - In automatic mode (`manualDie` is null) the card keeps the ladder move
 *   `d{currentDie} -> d{predictedDie}` and its die-size glossary link.
 */
export function DecisionCard({
  activeRatingThread,
  currentDie,
  rating,
  predictedDie,
  errorMessage,
  rateIsPending,
  dismissIsPending,
  manualDie,
  onUpdateRating,
  onSubmitRating,
  onReroll,
  rerollIsPending = false,
  onCancel,
  onResetDice,
}: DecisionCardProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const isLastIssue = issuesRemaining === 1
  const threadTitle = activeRatingThread?.title ?? null
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null

  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    setCopyStatus('idle')
  }, [threadTitle, issueNumber])

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
        <h3
          id="decision-heading"
          className="text-base font-bold text-[var(--theme-text-primary)]"
        >
          Your rating
        </h3>
        {threadTitle && issueNumber != null && (
          <button
            type="button"
            onClick={handleCopyComicReference}
            disabled={!threadTitle}
            className={`min-h-9 shrink-0 ${rollUtilityActionClass(copyStatus)}`}
            aria-label={`Copy ${threadTitle} ${issueNumber}`}
            aria-live="polite"
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
            {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry' : 'Copy title'}
          </button>
        )}
      </div>

      {copyStatus === 'failed' ? (
        <p role="status" className="text-[10px] font-bold text-[var(--theme-danger)]">
          Copy failed. Use Retry to try again.
        </p>
      ) : null}

      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <p id="rating-value" className={`text-5xl font-black ${getRatingColorClass(rating)}`}>
            {rating.toFixed(1)}
          </p>
          {manualDie !== null ? (
            <p className="text-[11px] font-bold text-stone-400">
              Manual mode is active at d{currentDie}
            </p>
          ) : (
            <p className="text-[11px] font-bold text-stone-400">
              <GlossaryLink id="die-size">d{currentDie} → d{predictedDie}</GlossaryLink>
            </p>
          )}
        </div>
      </div>

      <ComicIssueRatingSlider
        value={rating}
        onChange={onUpdateRating}
        inputId="rating-input"
        describedBy="rating-value queue-effect"
        showScaleNote={false}
        showValue={false}
      />

      <p id="queue-effect" className="text-[11px] font-bold leading-relaxed text-stone-400">
        {rating >= RATING_THRESHOLD
          ? 'Moves this series to the front of the queue.'
          : 'Moves this series beyond the next roll range.'}
      </p>

      {isLastIssue && (
        <div className="rounded-xl border border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/10 p-3 text-center">
          <p className="text-xs font-semibold text-[var(--theme-warning)]">
            This is the last issue in the series
          </p>
        </div>
      )}

      {errorMessage ? (
        <div id="error-message" className="text-center text-[10px] font-bold text-[var(--theme-danger)]" role="alert">
          {errorMessage}
          {errorMessage.startsWith('No other eligible comics remain.') && onResetDice ? (
            <button type="button" className={`${rollSecondaryActionClass} mt-2`} onClick={onResetDice}>
              Reset Dice
            </button>
          ) : null}
        </div>
      ) : null}

      <div
        className="w-full space-y-2 pt-3 pb-3 md:pt-1 md:pb-0 border-t border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-0 surface-glass"
        data-testid="rating-actions"
      >
        <button
          type="button"
          onClick={() => onSubmitRating(false)}
          disabled={rateIsPending}
          data-testid="save-and-continue"
          className={rollPrimaryActionClass}
        >
          {rateIsPending ? 'Saving…' : isLastIssue ? 'Mark read & complete' : 'Mark read & save'}
        </button>

        <div
          className={rollSecondaryActionGroupClass}
          data-testid="rating-secondary-actions"
        >
          {onReroll && (
            <button
              type="button"
              onClick={() => { void onReroll() }}
              disabled={rerollIsPending}
              data-testid="reroll-offer"
              className={rollSecondaryActionClass}
            >
              {rerollIsPending ? 'Rolling…' : 'Roll again'}
            </button>
          )}
          <button
            type="button"
            onClick={onCancel}
            disabled={dismissIsPending}
            data-testid="cancel-roll"
            className={rollSecondaryActionClass}
          >
            Cancel roll
          </button>
        </div>
      </div>
    </section>
  )
}