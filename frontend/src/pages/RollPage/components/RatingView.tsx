import { useState } from 'react'
import type { RatingViewData } from '../useRatingView'
import {
  ROLL_WORKSPACE_GUTTER,
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../workspaceLayout'
import { ComicPillar } from './ComicPillar'
import { DecisionCard } from './DecisionCard'
import { ReadingContextCard } from './ReadingContextCard'
import { ReadingBoundariesCard } from './ReadingBoundariesCard'
import { readingContextType } from '../readingContextTypography'

interface RatingViewProps {
  data: RatingViewData
}

export function RatingView({ data }: RatingViewProps) {
  const {
    activeRatingThread,
    currentDie,
    rolledResult: _rolledResult,
    rating,
    predictedDie,
    errorMessage,
    rateIsPending,
    snoozeIsPending,
    dismissIsPending,
    skipIsPending,
    onUpdateRating,
    onSubmitRating,
    onSnooze,
    onSkip,
    onCancel,
    onRefreshThread,
    readerContext,
    isReaderContextLoading,
    ratingViewTopRef,
  } = data

  const [isReadingContextOpen, setIsReadingContextOpen] = useState(false)
  const [isReadingBoundariesOpen, setIsReadingBoundariesOpen] = useState(false)

  const handleReadingContextToggle = () => setIsReadingContextOpen((prev) => !prev)
  const handleReadingBoundariesToggle = () =>
    setIsReadingBoundariesOpen((prev) => !prev)

  return (
    <div ref={ratingViewTopRef} data-testid="rating-view-top" className="relative z-10 space-y-4 p-3 md:p-4">
      <div
        className={`grid items-start ${ROLL_WORKSPACE_GUTTER} ${ROLL_WORKSPACE_MAX_WIDTH} lg:justify-center ${ROLL_WORKSPACE_TRACKS}`}
        data-testid="rating-pillars-grid"
      >
        <div className="min-w-0" data-testid="rating-region-comic">
          <ComicPillar activeRatingThread={activeRatingThread} onRefreshThread={onRefreshThread} />
        </div>

        <div className="min-w-0 space-y-4 w-full lg:w-auto lg:sticky lg:top-4" data-testid="rating-region-decision">
          <DecisionCard
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rating={rating}
            predictedDie={predictedDie}
            errorMessage={errorMessage}
            rateIsPending={rateIsPending}
            snoozeIsPending={snoozeIsPending}
            dismissIsPending={dismissIsPending}
            skipIsPending={skipIsPending}
            onUpdateRating={onUpdateRating}
            onSubmitRating={onSubmitRating}
            onSnooze={onSnooze}
            onSkip={onSkip}
            onCancel={onCancel}
          />

          <ReadingContextCard
            isLoading={isReaderContextLoading}
            error={readerContext ? null : 'Local reading context unavailable'}
            isOpen={isReadingContextOpen}
            onToggle={handleReadingContextToggle}
          >
            {readerContext && (
              <div>
                <span
                  className="text-[11px] text-stone-400"
                  style={readingContextType('bodyCopy')}
                >
                  See how this issue fits into your reading plans and continuity.
                </span>
              </div>
            )}
          </ReadingContextCard>

          <ReadingBoundariesCard
            isLoading={isReaderContextLoading}
            error={readerContext ? null : 'Local reading context unavailable'}
            readerContext={readerContext}
            isOpen={isReadingBoundariesOpen}
            onToggle={handleReadingBoundariesToggle}
          />
        </div>
      </div>
    </div>
  )
}
