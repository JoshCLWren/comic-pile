import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { YourContextPillar } from './YourContextPillar'
import { RatingActionPanel } from './RatingActionPanel'
import type { RatingViewData } from '../useRatingView'

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
    issuesRemaining,
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

        <div className="min-w-0 space-y-4" data-testid="rating-region-your-context">
          <YourContextPillar
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rating={rating}
            predictedDie={predictedDie}
            onUpdateRating={onUpdateRating}
            readerContext={readerContext}
            isLoading={isReaderContextLoading}
          />

          <div className="min-w-0" data-testid="rating-actions-grid-cell">
            <RatingActionPanel
              errorMessage={errorMessage}
              rateIsPending={rateIsPending}
              snoozeIsPending={snoozeIsPending}
              dismissIsPending={dismissIsPending}
              skipIsPending={skipIsPending}
              issuesRemaining={issuesRemaining}
              onSubmitRating={onSubmitRating}
              onSnooze={onSnooze}
              onSkip={onSkip}
              onCancel={onCancel}
              threadTitle={activeRatingThread?.title ?? null}
              issueNumber={activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
