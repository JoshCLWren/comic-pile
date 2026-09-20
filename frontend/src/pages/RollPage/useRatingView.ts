import { useReaderContext } from '../../hooks/useReaderContext'
import { computePredictedDie } from './utils'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { RatingThread } from './types'
import type { ReaderContextResponse } from '../../types'

interface UseRatingViewParams {
  state: RollPageState & RollPageStateSetters
  readingDetailsRequested: boolean
  rating: {
    updateRatingUI: (value: string) => void
    handleSubmitRating: (finishSession: boolean) => Promise<void>
    handleCancelRating: () => Promise<void>
    handleRefreshThread: () => Promise<void>
    enterRatingView: (threadId: number | null, result?: number | null, threadMetadata?: any) => Promise<void>
  }
  snooze: { handleSnooze: () => Promise<void> }
  onSkip: () => Promise<void>
  rateMutation: { isPending: boolean }
  snoozeMutation: { isPending: boolean }
  dismissPendingMutation: { isPending: boolean }
  skipMutation: { isPending: boolean }
  ratingViewTopRef: React.RefObject<HTMLDivElement | null> | null
}

export interface RatingViewData {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending: boolean
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
  onCancel: () => void
  onRefreshThread: () => void
  readerContext: ReaderContextResponse | null
  isReaderContextLoading: boolean
  readerContextError: Error | null
  ratingViewTopRef: React.RefObject<HTMLDivElement | null> | null
  issuesRemaining: number
}

/**
 * Colocates server-derived rating context for RatingView.
 *
 * Moves the useReaderContext call from RollPage into this hook,
 * computing the rating-issue ID from the active thread and the
 * reading-details-requested flag from useRollRating. This reduces
 * RatingView's prop surface from 20+ individual props to a single
 * data object consumed by the hook.
 */
export function useRatingView({
  state,
  readingDetailsRequested,
  rating,
  snooze,
  onSkip,
  rateMutation,
  snoozeMutation,
  dismissPendingMutation,
  skipMutation,
  ratingViewTopRef,
}: UseRatingViewParams): RatingViewData {
  const {
    activeRatingThread,
    currentDie,
    rolledResult,
    rating: ratingValue,
    errorMessage,
  } = state

  const ratingIssueId =
    activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id ?? null

  const {
    context: readerContext,
    isLoading: isReaderContextLoading,
    error: readerContextError,
  } = useReaderContext(ratingIssueId, readingDetailsRequested)

  const predictedDie = computePredictedDie(currentDie, ratingValue)

  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0

  return {
    activeRatingThread,
    currentDie,
    rolledResult,
    rating: ratingValue,
    predictedDie,
    errorMessage,
    rateIsPending: rateMutation.isPending,
    snoozeIsPending: snoozeMutation.isPending,
    dismissIsPending: dismissPendingMutation.isPending,
    skipIsPending: skipMutation.isPending,
    onUpdateRating: rating.updateRatingUI,
    onSubmitRating: rating.handleSubmitRating,
    onSnooze: snooze.handleSnooze,
    onSkip,
    onCancel: rating.handleCancelRating,
    onRefreshThread: rating.handleRefreshThread,
    readerContext,
    isReaderContextLoading,
    readerContextError: readerContextError ?? null,
    ratingViewTopRef,
    issuesRemaining,
  }
}
