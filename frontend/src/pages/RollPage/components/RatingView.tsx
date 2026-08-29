import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo, ReaderContextResponse } from '../../../types'
import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { ReadingContextPillar } from './ReadingContextPillar'
import { YourContextPillar } from './YourContextPillar'
import { RatingActionPanel } from './RatingActionPanel'
import { WhyThisRoll } from './WhyThisRoll'

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
  readerContext?: ReaderContextResponse | null
  isReaderContextLoading?: boolean
  readerContextError?: string | null
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
  readerContext = null,
  isReaderContextLoading = false,
  readerContextError = null,
}: RatingViewProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const hasReadingContextContent = readingOrders.length > 0 || connectedThreads.length > 0
  const gridCols = hasReadingContextContent
    ? 'xl:grid-cols-[minmax(0,26fr)_minmax(0,46fr)_minmax(0,28fr)]'
    : 'xl:grid-cols-[minmax(0,50fr)_minmax(0,50fr)]'

  return (
    <div className="relative z-10 space-y-4 p-3 md:p-4">
      <WhyThisRoll explanation={activeRatingThread?.explanation} />
      <div className={`grid gap-4 md:grid-cols-2 md:gap-6 ${gridCols}`} data-testid="rating-pillars-grid">
        <div className="md:row-span-2 xl:row-span-1">
          <ComicPillar
            activeRatingThread={activeRatingThread}
            onRefreshThread={onRefreshThread}
          />
        </div>

        {hasReadingContextContent && (
          <ReadingContextPillar
            activeRatingThread={activeRatingThread}
            readingOrders={readingOrders}
            connectedThreads={connectedThreads}
            onRefreshThread={onRefreshThread}
            rolledResult={rolledResult}
            currentDie={currentDie}
            readerContext={readerContext}
            isReaderContextLoading={isReaderContextLoading}
            readerContextError={readerContextError}
          />
        )}

        <YourContextPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rating={rating}
          predictedDie={predictedDie}
          onUpdateRating={onUpdateRating}
          readerContext={readerContext}
          isLoading={isReaderContextLoading}
        />

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
