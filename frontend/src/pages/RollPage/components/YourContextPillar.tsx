import { RATING_THRESHOLD } from '../utils'
import type { RatingThread } from '../types'

interface YourContextPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rating: number
  predictedDie: number
  onSnooze: () => void
  onCancel: () => void
}

export function YourContextPillar({
  activeRatingThread,
  currentDie,
  rating,
  predictedDie,
  onSnooze,
  onCancel,
}: YourContextPillarProps) {
  let dieDirection: string
  if (predictedDie < currentDie) dieDirection = 'More focused next roll'
  else if (predictedDie > currentDie) dieDirection = 'More variety next roll'
  else dieDirection = 'Die stays the same'

  const isLastIssue = activeRatingThread?.issues_remaining === 1

  return (
    <div className="w-full space-y-4">
      {activeRatingThread ? (
        <div className="space-y-3 rounded-2xl border border-white/10 bg-black/10 p-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Your rating</span>
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
            onChange={(event) => onUpdateRating(event.target.value)}
          />
          <p className="text-[11px] font-bold leading-relaxed text-stone-400">
            {rating >= RATING_THRESHOLD
              ? 'Moves this thread to the front of the queue.'
              : 'Moves this thread beyond the next roll range.'}
          </p>
        </div>
      ) : null}

      <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
        <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
          {isLastIssue ? 'This is the last issue in the thread' : ''}
        </p>
      </div>

      <div className="space-y-3">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">Series statistics</p>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="text-[10px] font-black text-stone-500">Issues read</p>
              <p className="text-2xl font-black text-stone-100">24</p>
            </div>
            <div>
              <p className="text-[10px] font-black text-stone-500">Progress</p>
              <p className="text-2xl font-black text-stone-100">67%</p>
            </div>
            <div>
              <p className="text-[10px] font-black text-stone-500">Avg rating</p>
              <p className="text-2xl font-black text-stone-100">3.5</p>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">Recent ratings</p>
          <div className="flex gap-1">
            <span className="text-[9px] font-black text-stone-400">4.0</span>
            <span className="text-[9px] font-black text-stone-400">3.5</span>
            <span className="text-[9px] font-black text-stone-400">4.5</span>
            <span className="text-[9px] font-black text-stone-400">3.0</span>
          </div>
        </div>

        {activeRatingThread?.connected_threads?.length > 0 ? (
          <div className="space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">Crossover stats</p>
            <div className="flex gap-1">
              <span className="text-[9px] font-black text-blue-400 rounded bg-blue-900/20 px-2 py-1">3 crossovers</span>
              <span className="text-[9px] font-black text-blue-400 rounded bg-blue-900/20 px-2 py-1">2 blocked</span>
            </div>
          </div>
        ) : null}

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">Actions</p>
          <div className="flex flex-col sm:flex-row gap-2">
            <button
              type="button"
              onClick={onSnooze}
              disabled={snoozeIsPending}
              className="flex-1 rounded-xl border border-white/10 bg-white/5 py-2.5 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
            >
              Snooze
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={dismissIsPending}
              className="flex-1 rounded-xl border border-rose-600/30 bg-rose-600/10 py-2.5 text-xs font-black uppercase tracking-[0.15em] text-rose-400 transition hover:bg-rose-600/20 focus:ring-2 focus:ring-rose-500 disabled:opacity-50"
            >
              Cancel roll
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}