import { PillarHeader } from './PillarHeader'
import Tooltip from '../../../components/Tooltip'
import { RATING_THRESHOLD } from '../utils'
import type { RatingThread } from '../types'

const ACCENT = 'var(--your-context-accent, #9333ea)'

function getDieDirection(currentDie: number, predictedDie: number): string {
  if (predictedDie < currentDie) return 'More focused next roll'
  if (predictedDie > currentDie) return 'More variety next roll'
  return 'Die stays the same'
}

interface YourContextPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  predictedDie: number
  rating: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  issuesRemaining: number
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
}

export function YourContextPillar({
  activeRatingThread,
  currentDie,
  predictedDie,
  rating,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  issuesRemaining,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
}: YourContextPillarProps) {
  const dieDirection = getDieDirection(currentDie, predictedDie)

  return (
    <div className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3 md:p-4">
      <PillarHeader number="03" title="Your Context" accentColor={ACCENT} />

      <section aria-labelledby="rating-heading" className="space-y-3 rounded-xl border border-white/10 bg-black/10 p-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the thread to the front and step the die down. Lower ratings move it past the next roll range and step the die up.`}>
              <h3 id="rating-heading" className="cursor-help text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                Your rating
              </h3>
            </Tooltip>
            <p id="rating-value" className={`mt-1 text-4xl font-black ${rating >= RATING_THRESHOLD ? 'text-amber-500' : 'text-red-600'}`}>
              {rating.toFixed(1)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm font-black text-stone-200">d{currentDie} → d{predictedDie}</p>
            <p className="text-[10px] font-bold text-stone-500">{dieDirection}</p>
          </div>
        </div>
        <input
          type="range"
          id="rating-input"
          name="rating"
          min="0.5"
          max="5.0"
          step="0.5"
          value={rating}
          className="h-4 w-full"
          aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
          aria-describedby="rating-value queue-effect"
          onChange={(event) => onUpdateRating(event.target.value)}
        />
        <p id="queue-effect" className="text-[11px] font-bold leading-relaxed text-stone-400">
          {rating >= RATING_THRESHOLD
            ? 'Moves this thread to the front of the queue.'
            : 'Moves this thread beyond the next roll range.'}
        </p>
      </section>

      {activeRatingThread?.issues_remaining === 1 ? (
        <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
            This is the last issue in the thread
          </p>
        </div>
      ) : null}

      <div
        className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-white/10 bg-[#1a1410]/95 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3"
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
    </div>
  )
}
