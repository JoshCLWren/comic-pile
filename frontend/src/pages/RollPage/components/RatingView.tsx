import { useState } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import Tooltip from '../../../components/Tooltip'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import { RATING_THRESHOLD, getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicVineIssueCard } from './ComicVineIssueCard'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'
import { ComicPillar } from './ComicPillar'
import { ReadingContextPillar } from './ReadingContextPillar'
import { YourContextPillar } from './YourContextPillar'
import { RatingActionPanel } from './RatingActionPanel'

function getDieDirection(currentDie: number, predictedDie: number): string {
  if (predictedDie < currentDie) return 'More focused next roll'
  if (predictedDie > currentDie) return 'More variety next roll'
  return 'Die stays the same'
}

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
  const [isCorrectionDialogOpen, setIsCorrectionDialogOpen] = useState(false)
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)
  const dieDirection = getDieDirection(currentDie, predictedDie)

  async function handleCopyComicReference() {
    if (!activeRatingThread?.title || issueNumber == null) return

    try {
      await navigator.clipboard.writeText(`${activeRatingThread.title} ${issueNumber}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  return (
    <div className="w-full space-y-4">
      <div className="grid md:grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
        <ComicPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rolledResult={rolledResult}
          rating={rating}
          predictedDie={predictedDie}
          hasValidRolledResult={hasValidRolledResult}
          poolSize={poolSize}
          errorMessage={errorMessage}
          rateIsPending={rateIsPending}
          snoozeIsPending={snoozeIsPending}
          dismissIsPending={dismissIsPending}
          readingOrders={readingOrders}
          connectedThreads={connectedThreads}
          onUpdateRating={onUpdateRating}
          onSubmitRating={onSubmitRating}
          onSnooze={onSnooze}
          onCancel={onCancel}
        />

        <ReadingContextPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rolledResult={rolledResult}
          rating={rating}
          predictedDie={predictedDie}
          hasValidRolledResult={hasValidRolledResult}
          poolSize={poolSize}
          errorMessage={errorMessage}
          rateIsPending={rateIsPending}
          snoozeIsPending={snoozeIsPending}
          dismissIsPending={dismissIsPending}
          readingOrders={readingOrders}
          connectedThreads={connectedThreads}
          onUpdateRating={onUpdateRating}
          onSubmitRating={onSubmitRating}
          onSnooze={onSnooze}
          onCancel={onCancel}
        />

        <YourContextPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rating={rating}
          predictedDie={predictedDie}
          onSnooze={onSnooze}
          onCancel={onCancel}
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