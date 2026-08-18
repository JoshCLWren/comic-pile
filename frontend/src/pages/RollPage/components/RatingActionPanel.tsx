interface RatingActionPanelProps {
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  issuesRemaining: number
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
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
}: RatingActionPanelProps) {
  return (
    <div
      className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-white/10 bg-white/[0.04] px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3"
      data-testid="rating-actions"
    >
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
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onSnooze}
          disabled={snoozeIsPending}
          className="min-h-11 flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
        >
          {snoozeIsPending ? 'Snoozing…' : 'Snooze'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={dismissIsPending}
          className="min-h-11 flex-1 rounded-xl border border-rose-600/30 bg-rose-600/10 py-3 text-xs font-black uppercase tracking-[0.15em] text-rose-400 transition hover:bg-rose-600/20 focus:ring-2 focus:ring-rose-500 disabled:opacity-50"
        >
          Cancel roll
        </button>
      </div>
    </div>
  )
}