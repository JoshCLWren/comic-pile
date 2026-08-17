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
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="pillar-cockpit">
        <ComicPillar
          activeRatingThread={activeRatingThread}
          hasValidRolledResult={hasValidRolledResult}
          rolledResult={rolledResult}
          currentDie={currentDie}
          poolSize={poolSize}
          onRefreshThread={onRefreshThread}
        />

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

        <RatingActionPanel
          issuesRemaining={issuesRemaining}
          rateIsPending={rateIsPending}
          snoozeIsPending={snoozeIsPending}
          dismissIsPending={dismissIsPending}
          errorMessage={errorMessage}
          onSubmitRating={onSubmitRating}
          onSnooze={onSnooze}
          onCancel={onCancel}
        />
      </div>
    </div>
  )
}
