import { useState } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { ReadingContextPillar } from './ReadingContextPillar'
import { YourContextPillar } from './YourContextPillar'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'

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
  const [isCorrectionDialogOpen, setIsCorrectionDialogOpen] = useState(false)
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0

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
    <div className="relative z-10 space-y-4 p-3 md:p-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[26fr_46fr_28fr]">
        <ComicPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          rolledResult={rolledResult}
          hasValidRolledResult={hasValidRolledResult}
          poolSize={poolSize}
          copyStatus={copyStatus}
          onCopy={handleCopyComicReference}
          onEditIssue={() => setIsCorrectionDialogOpen(true)}
        />

        <ReadingContextPillar
          threadId={activeRatingThread?.id}
          connectedThreads={connectedThreads}
          readingOrders={readingOrders}
          threadTitle={threadTitle}
          issueNumber={issueNumber}
          onExplainRoute={() => setIsRouteExplanationOpen(true)}
          onCorrectContinuity={() => setIsContinuityDialogOpen(true)}
        />

        <YourContextPillar
          activeRatingThread={activeRatingThread}
          currentDie={currentDie}
          predictedDie={predictedDie}
          rating={rating}
          errorMessage={errorMessage}
          rateIsPending={rateIsPending}
          snoozeIsPending={snoozeIsPending}
          dismissIsPending={dismissIsPending}
          issuesRemaining={issuesRemaining}
          onUpdateRating={onUpdateRating}
          onSubmitRating={onSubmitRating}
          onSnooze={onSnooze}
          onCancel={onCancel}
        />
      </div>

      <ReadingRouteExplanation
        isOpen={isRouteExplanationOpen}
        issueId={issueId}
        issueLabel={`${threadTitle}${issueNumber != null ? ` #${issueNumber}` : ''}`}
        readingOrders={readingOrders}
        connectedThreads={connectedThreads}
        onClose={() => setIsRouteExplanationOpen(false)}
      />

      {activeRatingThread ? (
        <IssueCorrectionDialog
          isOpen={isCorrectionDialogOpen}
          threadId={activeRatingThread.id}
          currentIssueNumber={activeRatingThread.next_issue_number ?? activeRatingThread.issue_number}
          totalIssues={activeRatingThread.total_issues}
          threadTitle={activeRatingThread.title}
          onClose={() => setIsCorrectionDialogOpen(false)}
          onSuccess={() => {
            setIsCorrectionDialogOpen(false)
            onRefreshThread()
          }}
        />
      ) : null}

      {activeRatingThread ? (
        <ContinuityCorrectionDialog
          isOpen={isContinuityDialogOpen}
          threadId={activeRatingThread.id}
          issueId={issueId}
          issueNumber={issueNumber}
          threadTitle={activeRatingThread.title}
          connectedThreads={connectedThreads}
          onClose={() => setIsContinuityDialogOpen(false)}
          onSuccess={() => {
            setIsContinuityDialogOpen(false)
            onRefreshThread()
          }}
        />
      ) : null}
    </div>
  )
}
