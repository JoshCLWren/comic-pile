import GlossaryLink from '../../../components/GlossaryLink'
import type { ReaderContextResponse } from '../../../services/api-reader-context'
import { RATING_THRESHOLD, getRatingColorClass } from '../utils'
import type { RatingThread } from '../types'
import { SeriesPanel } from './SeriesPanel'
import { CrossoverAnalytics } from './CrossoverAnalytics'

interface YourContextPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rating: number
  predictedDie: number
  onUpdateRating: (value: string) => void
  readerContext: ReaderContextResponse | null
  isLoading: boolean
}

function ReaderContextLoading() {
  return (
    <div className="space-y-2 rounded-2xl border border-[var(--theme-personal-accent)]/10 bg-[var(--theme-bg-panel)] p-3">
      <div className="h-3 w-24 animate-pulse rounded bg-[var(--theme-bg-hover)]" />
      <div className="h-5 w-16 animate-pulse rounded bg-[var(--theme-bg-hover)]" />
      <div className="h-3 w-20 animate-pulse rounded bg-[var(--theme-bg-hover)]" />
    </div>
  )
}

export function YourContextPillar({
  activeRatingThread,
  currentDie,
  rating,
  predictedDie,
  onUpdateRating,
  readerContext,
  isLoading,
}: YourContextPillarProps) {
  const isLastIssue = activeRatingThread?.issues_remaining === 1
  const hasMeaningfulContext = isLoading || readerContext !== null || isLastIssue

  return (
    <div className="w-full space-y-4">
      {hasMeaningfulContext && (
        <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-personal-accent)' }}>
          <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-personal-accent)' }}>Your Context</span>
        </div>
      )}

      {isLoading ? <ReaderContextLoading /> : null}

      {readerContext ? (
        <>
          <SeriesPanel series={readerContext.series} />
          <CrossoverAnalytics crossovers={readerContext.crossovers} />
        </>
      ) : null}

      <section aria-labelledby="rating-heading" className="space-y-3 rounded-2xl border border-[var(--theme-personal-accent)]/20 bg-[var(--theme-bg-panel)] p-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h3 id="rating-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--theme-text-dim)]">
              Your rating
            </h3>
            <p id="rating-value" className={`mt-1 text-4xl font-black ${getRatingColorClass(rating)}`}>
              {rating.toFixed(1)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm font-black text-[var(--theme-text-primary)]">
              <GlossaryLink id="die-size">d{currentDie} → d{predictedDie}</GlossaryLink>
            </p>
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
        <p id="queue-effect" className="text-[11px] font-bold leading-relaxed text-[var(--theme-text-muted)]">
          {rating >= RATING_THRESHOLD
            ? 'Moves this series to the front of the queue.'
            : 'Moves this series beyond the next roll range.'}
        </p>
      </section>

      {isLastIssue ? (
        <div className="rounded-xl border border-[var(--theme-comic-accent)]/20 bg-[var(--theme-comic-accent)]/10 p-3 text-center">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-[var(--theme-comic-accent)]">
            This is the last issue in the series
          </p>
        </div>
      ) : null}
    </div>
  )
}
