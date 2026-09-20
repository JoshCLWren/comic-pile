import { type Ref } from 'react'
import type { ReaderContextResponse } from '../../../types'
import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { DecisionCard } from './DecisionCard'
import { ContextDisclosure } from './ContextDisclosure'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending?: boolean
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
  onCancel: () => void
  onRefreshThread: () => void
  readerContext?: ReaderContextResponse | null
  isReaderContextLoading?: boolean
  readerContextError?: string | null
  ratingViewTopRef?: Ref<HTMLDivElement> | null
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult: _rolledResult,
  rating,
  predictedDie,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  skipIsPending = false,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onSkip,
  onCancel,
  onRefreshThread,
  readerContext = null,
  isReaderContextLoading = false,
  ratingViewTopRef = null,
}: RatingViewProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0

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