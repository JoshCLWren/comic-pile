import { useEffect, useState } from 'react'
import Modal from '../../../components/Modal'

interface RatingActionPanelProps {
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending?: boolean
  issuesRemaining: number
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
  onCancel: () => void
  threadTitle?: string | null
  issueNumber?: string | null
}

export function RatingActionPanel({
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  skipIsPending = false,
  issuesRemaining,
  onSubmitRating,
  onSnooze,
  onSkip,
  onCancel,
  threadTitle = null,
  issueNumber = null,
}: RatingActionPanelProps) {
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
    <div
      className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-white/10 bg-white/[0.04] px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3"
      data-testid="rating-actions"
    >
      {threadTitle && issueNumber != null ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="copy-title-row">
          <button
            type="button"
            onClick={handleCopyComicReference}
            disabled={!threadTitle}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[10px] font-black uppercase tracking-wider text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-amber-500 disabled:opacity-40"
            aria-label={`Copy ${threadTitle} ${issueNumber}`}
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
          <p className="text-[10px] font-semibold text-[var(--theme-text-dim)]">
            Copies “{threadTitle} {issueNumber}”
          </p>
          {copyStatus === 'failed' ? (
            <p className="text-[10px] font-bold text-rose-400" role="status">
              Copy failed. Use Retry copy to try again.
            </p>
          ) : null}
        </div>
      ) : null}
      {errorMessage ? (
        <div id="error-message" className="text-center text-[10px] font-bold text-rose-500" role="alert">
          {errorMessage}
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => onSubmitRating(false)}
        disabled={rateIsPending}
        data-testid="save-and-continue"
        className="w-full rounded-xl border border-amber-600/50 bg-amber-600/25 py-3.5 text-xs font-black uppercase tracking-[0.15em] transition hover:bg-amber-600/35 focus:ring-2 focus:ring-amber-500 disabled:opacity-50 active:scale-[0.98]"
      >
        {rateIsPending ? 'Saving…' : issuesRemaining === 1 ? 'Mark read & complete' : 'Mark read & save'}
      </button>
      <div className="flex flex-wrap gap-2" data-testid="rating-secondary-actions">
        <button
          type="button"
          onClick={onSnooze}
          disabled={snoozeIsPending}
          className="min-h-11 min-w-[7.5rem] flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
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
            className="min-h-11 min-w-[7.5rem] flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
          >
            {skipIsPending ? 'Skipping…' : 'Skip'}
          </button>
        )}
        <button
          type="button"
          onClick={onCancel}
          disabled={dismissIsPending}
          className="min-h-11 min-w-[7.5rem] flex-1 rounded-xl border border-[var(--theme-border)] bg-transparent py-3 text-xs font-black uppercase tracking-[0.15em] text-[var(--theme-text-muted)] transition hover:bg-white/10 hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
        >
          Cancel roll
        </button>
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
    </div>
  )
}
