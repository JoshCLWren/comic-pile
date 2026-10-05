import type { RatingViewData } from '../useRatingView'
import {
  ROLL_WORKSPACE_GUTTER,
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../workspaceLayout'
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
    <div
      ref={ratingViewTopRef}
      id="rating-view-top"
      data-testid="rating-view-top"
      tabIndex={-1}
      className="relative z-10 space-y-4 p-3 md:p-4 focus:outline-none"
    >
      <div
        className={`grid items-start ${ROLL_WORKSPACE_GUTTER} ${ROLL_WORKSPACE_MAX_WIDTH} lg:justify-center ${ROLL_WORKSPACE_TRACKS}`}
        data-testid="rating-pillars-grid"
      >
        <div className="min-w-0" data-testid="rating-region-comic">
          <ComicPillar
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            onRefreshThread={onRefreshThread}
          />
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
            manualDie={data.manualDie}
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
