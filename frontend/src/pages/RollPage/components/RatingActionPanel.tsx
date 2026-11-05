import { useEffect, useState } from 'react'
import {
  rollPrimaryActionClass,
  rollSecondaryActionClass,
  rollSecondaryActionGroupClass,
  rollUtilityActionClass,
} from '../actionClasses'

interface RatingActionPanelProps {
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  issuesRemaining: number
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  threadTitle?: string | null
  issueNumber?: string | null
}

export function RatingActionPanel({
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  issuesRemaining,
  onSubmitRating,
  onSnooze,
  onCancel,
  threadTitle = null,
  issueNumber = null,
}: RatingActionPanelProps) {
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
    <div
      className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+3rem)] surface-glass md:static md:-mx-4 md:px-4 md:pb-3"
      data-testid="rating-actions"
    >
      {threadTitle && issueNumber != null ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="copy-title-row">
          <button
            type="button"
            onClick={handleCopyComicReference}
            disabled={!threadTitle}
            className={`min-h-11 ${rollUtilityActionClass(copyStatus)}`}
            aria-label={`Copy ${threadTitle} ${issueNumber}`}
            aria-live="polite"
          >
            <svg
              className="h-4 w-4 shrink-0"
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
            {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy title'}
          </button>
          <p className="text-[10px] font-medium text-[var(--theme-text-dim)]">
            Copies “{threadTitle} {issueNumber}”
          </p>
          {copyStatus === 'failed' ? (
            <p className="text-[10px] font-bold text-[var(--theme-danger)]" role="status">
              Copy failed. Use Retry copy to try again.
            </p>
          ) : null}
        </div>
      ) : null}
      {errorMessage ? (
        <div id="error-message" className="text-center text-[10px] font-bold text-[var(--theme-danger)]" role="alert">
          {errorMessage}
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => onSubmitRating(false)}
        disabled={rateIsPending}
        data-testid="save-and-continue"
        className={rollPrimaryActionClass}
      >
        {rateIsPending ? 'Saving…' : issuesRemaining === 1 ? 'Mark read & complete' : 'Mark read & save'}
      </button>
      <div className={rollSecondaryActionGroupClass} data-testid="rating-secondary-actions">
        <button
          type="button"
          onClick={onSnooze}
          disabled={snoozeIsPending}
          className={rollSecondaryActionClass}
        >
          {snoozeIsPending ? 'Snoozing…' : 'Snooze'}
        </button>
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
  )
}
