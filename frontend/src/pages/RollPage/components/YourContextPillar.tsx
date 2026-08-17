import Tooltip from '../../../components/Tooltip'
import { RATING_THRESHOLD } from '../utils'
import type { RatingThread } from '../types'

function getDieDirection(currentDie: number, predictedDie: number): string {
  if (predictedDie < currentDie) return 'More focused next roll'
  if (predictedDie > currentDie) return 'More variety next roll'
  return 'Die stays the same'
}

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

  return (
    <div className="pillar-your">
      <div className="pillar-header">
        <span className="pillar-number">03</span>
        <span>Your Context</span>
      </div>
      <div className="pillar-panel">
        <section aria-labelledby="rating-heading" className="space-y-3 rounded-2xl border border-white/10 bg-black/10 p-3">
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
      </div>
    </div>
  )
}
