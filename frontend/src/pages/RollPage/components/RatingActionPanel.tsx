import { RATING_THRESHOLD } from '../utils'
import { getDieDirection } from '../utils'

interface RatingActionPanelProps {
  rating: number
  currentDie: number
  predictedDie: number
  issuesRemaining: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
}

export function RatingActionPanel({
  rating,
  currentDie,
  predictedDie,
  issuesRemaining,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
}: RatingActionPanelProps) {
  const dieDirection = getDieDirection(currentDie, predictedDie)

  return (
    <div
      className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-[var(--theme-panel-border)] bg-[#1a1410]/95 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3"
      data-testid="rating-actions"
    >
      {errorMessage ? (
        <div
          id="error-message"
          className="text-center text-[10px] font-bold"
          style={{ color: 'var(--theme-danger)' }}
          role="alert"
        >
          {errorMessage}
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => onSubmitRating(false)}
        disabled={rateIsPending}
        data-testid="save-and-continue"
        className="w-full rounded-xl border border-[var(--theme-primary-action)] py-3.5 text-xs font-black uppercase tracking-[0.15em] transition focus:ring-2 disabled:opacity-50 active:scale-[0.98]"
        style={{
          backgroundColor: 'rgba(212, 137, 14, 0.25)',
          '--tw-border-opacity': 1,
          '--tw-bg-opacity': 1,
          '--tw-ring-color': 'var(--theme-primary-action)',
        } as React.CSSProperties}
      >
        {rateIsPending ? 'Saving…' : issuesRemaining === 1 ? 'Mark read & complete' : 'Mark read & save'}
      </button>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onSnooze}
          disabled={snoozeIsPending}
          className="min-h-11 flex-1 rounded-xl border border-[var(--theme-panel-border)] bg-white/5 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 disabled:opacity-50"
          style={{ '--tw-ring-color': 'var(--theme-comic-accent)' } as React.CSSProperties}
        >
          {snoozeIsPending ? 'Snoozing…' : 'Snooze'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={dismissIsPending}
          className="min-h-11 flex-1 rounded-xl border py-3 text-xs font-black uppercase tracking-[0.15em] transition focus:ring-2 disabled:opacity-50"
          style={{
            backgroundColor: 'rgba(192, 57, 43, 0.10)',
            borderColor: 'rgba(192, 57, 43, 0.30)',
            color: 'var(--theme-danger)',
            '--tw-ring-color': 'var(--theme-danger)',
          } as React.CSSProperties}
        >
          {dismissIsPending ? 'Cancelling…' : 'Cancel roll'}
        </button>
      </div>
    </div>
  )
}
