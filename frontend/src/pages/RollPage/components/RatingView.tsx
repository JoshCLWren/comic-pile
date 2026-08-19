import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { ReadingContextPillar } from './ReadingContextPillar'
import { YourContextPillar } from './YourContextPillar'
import { RatingActionPanel } from './RatingActionPanel'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult: boolean
  poolSize: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  onRefreshThread: () => void
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  hasValidRolledResult,
  poolSize,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  readingOrders,
  connectedThreads,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
  onRefreshThread,
}: RatingViewProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0

  return (
    <div className="relative z-10 space-y-4 p-3 md:p-4">
      <div className="grid gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-[minmax(0,26fr)_minmax(0,46fr)_minmax(0,28fr)]" data-testid="rating-pillars-grid">
        <div className="md:row-span-2 xl:row-span-1">
          <ComicPillar
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rolledResult={rolledResult}
            poolSize={poolSize}
            hasValidRolledResult={hasValidRolledResult}
            onRefreshThread={onRefreshThread}
          />
        </div>

        <ReadingContextPillar
          activeRatingThread={activeRatingThread}
          readingOrders={readingOrders}
          connectedThreads={connectedThreads}
          onRefreshThread={onRefreshThread}
        />

        <YourContextPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rating={rating}
          predictedDie={predictedDie}
          onUpdateRating={onUpdateRating}
        />
      </div>

      <RatingActionPanel
        errorMessage={errorMessage}
        rateIsPending={rateIsPending}
        snoozeIsPending={snoozeIsPending}
        dismissIsPending={dismissIsPending}
        issuesRemaining={issuesRemaining}
        onSubmitRating={onSubmitRating}
        onSnooze={onSnooze}
        onCancel={onCancel}
      />
    </div>
  )
}
