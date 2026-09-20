import type { RatingViewData } from '../useRatingView'
import { ComicPillar } from './ComicPillar'
import { DecisionCard } from './DecisionCard'
import { ContextDisclosure } from './ContextDisclosure'

interface RatingViewProps {
  data: RatingViewData
}

export function RatingView({ data }: RatingViewProps) {
  const {
    activeRatingThread,
    currentDie,
    rolledResult,
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

  return (
    <div ref={ratingViewTopRef} data-testid="rating-view-top" className="relative z-10 space-y-4 p-3 md:p-4">
      <div
        className="grid items-start gap-4 lg:grid-cols-2 lg:gap-6"
        data-testid="rating-pillars-grid"
      >
        <div className="min-w-0" data-testid="rating-region-comic">
          <ComicPillar activeRatingThread={activeRatingThread} onRefreshThread={onRefreshThread} />
        </div>

        <div className="min-w-0 space-y-4" data-testid="rating-region-decision">
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

          <ContextDisclosure
            readerContext={readerContext}
            isLoading={isReaderContextLoading}
          />
        </div>
      </div>
    </div>
  )
}