import Tooltip from '../../../components/Tooltip'
import { RATING_THRESHOLD, getDieDirection } from '../utils'
import type { RatingThread } from '../types'

interface YourContextPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rating: number
  predictedDie: number
  onUpdateRating: (value: string) => void
}

export function YourContextPillar({
  activeRatingThread,
  currentDie,
  rating,
  predictedDie,
  onUpdateRating,
}: YourContextPillarProps) {
  const dieDirection = getDieDirection(currentDie, predictedDie)
  const isLastIssue = activeRatingThread?.issues_remaining === 1

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-personal-accent)' }}>
        <span className="text-[10px] font-black tabular-nums" style={{ color: 'var(--theme-personal-accent)' }}>03</span>
        <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-personal-accent)' }}>Your Context</span>
      </div>
      <section aria-labelledby="rating-heading" className="space-y-3 rounded-2xl p-3" style={{ border: '1px solid rgba(168,85,247,0.2)', backgroundColor: 'var(--theme-bg-panel)' }}>
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

      {isLastIssue ? (
        <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
            This is the last issue in the thread
          </p>
        </div>
      ) : null}
    </div>
  )
}
