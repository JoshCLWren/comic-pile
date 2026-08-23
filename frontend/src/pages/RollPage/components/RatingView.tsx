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
  hasValidRolledResult?: boolean
  poolSize?: number
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
    <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-3 p-3 md:gap-4 md:p-4">
      <div
        className="grid min-h-0 flex-1 gap-4 md:grid-cols-2 md:gap-6"
        data-testid="rating-pillars-grid"
      >
        {/* Left column: The Comic visual/identity column */}
        <div className="flex min-h-0 flex-col overflow-y-auto">
          <ComicPillar
            activeRatingThread={activeRatingThread}
            onRefreshThread={onRefreshThread}
          />
        </div>

        {/* Right column: Reading Context (primary) above Your Context, then actions below */}
        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          <ReadingContextPillar
            activeRatingThread={activeRatingThread}
            readingOrders={readingOrders}
            connectedThreads={connectedThreads}
            onRefreshThread={onRefreshThread}
            rolledResult={rolledResult}
            currentDie={currentDie}
          />

          <YourContextPillar
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rating={rating}
            predictedDie={predictedDie}
            onUpdateRating={onUpdateRating}
          />
        </div>
      </div>

        <div
          className={`md:col-span-2 md:row-start-3 xl:col-start-2 xl:row-start-2 ${
            hasReadingContextContent ? 'xl:col-span-2' : 'xl:col-end-3'
          }`}
          data-testid="rating-actions-grid-cell"
        >
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
      </div>
    </div>
  )
}
