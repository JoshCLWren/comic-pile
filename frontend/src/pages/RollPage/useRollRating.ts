import { useCallback, useState } from 'react'
import { DICE_LADDER } from '../../components/diceLadder'
import { dependenciesApi } from '../../services/api'
import { readingOrdersApi } from '../../services/api-reading-orders'
import { getApiErrorDetail } from '../../utils/apiError'
import type { ConnectedThreadInfo, RatePayload, Thread } from '../../types'
import type { ReadingOrder } from '../../services/api-reading-orders'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'
import { RATING_THRESHOLD, buildRatingThread, createExplosion } from './utils'

interface UseRollRatingParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse
  rateMutation: { mutate: (payload: RatePayload) => Promise<Thread | undefined>; isPending: boolean }
  dismissPendingMutation: { mutate: () => Promise<unknown>; isPending: boolean }
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  scrollToDice: () => void
}

/**
 * Owns the retained rating feature: entering the rating view from a roll,
 * pending read, stale read, or migration, plus submission, refresh, and
 * predicted-die feedback. Reading-order and connected-thread metadata live
 * here so the page never refetches them outside an explicit rating entry.
 */
export function useRollRating({
  state,
  bootstrap,
  rateMutation,
  dismissPendingMutation,
  refetchBootstrap,
  scrollToDice,
}: UseRollRatingParams) {
  const {
    activeRatingThread,
    currentDie,
    suppressPendingAutoOpenRef,
    rating,
    setActiveRatingThread,
    setErrorMessage,
    setIsActionSheetOpen,
    setIsDieModalOpen,
    setIsOverrideOpen,
    setIsRatingView,
    setIsRolling,
    setPredictedDie,
    setRating,
    setRolledResult,
    setSelectedThreadId,
    setShowMigrationDialog,
    setShowSimpleMigration,
    setThreadToMigrate,
  } = state

  const [readingOrders, setReadingOrders] = useState<ReadingOrder[]>([])
  const [connectedThreads, setConnectedThreads] = useState<ConnectedThreadInfo[]>([])

  const enterRatingView = useCallback(
    async (
      threadId: number | null,
      result: number | null = null,
      threadMetadata: ThreadMetadata | null = null,
    ) => {
      const ratingThread = buildRatingThread(threadId, result, threadMetadata, bootstrap?.active_thread)
      if (!ratingThread) {
        setErrorMessage('Unable to load the selected thread.')
        setIsRatingView(false)
        return
      }

      setIsActionSheetOpen(false)
      setIsOverrideOpen(false)
      setIsDieModalOpen(false)

      setSelectedThreadId(threadId)
      if (result !== null) setRolledResult(result)
      setActiveRatingThread(ratingThread)

      setRating(3.0)
      setErrorMessage('')
      const die = currentDie || 6
      const idx = DICE_LADDER.indexOf(die)
      const ratingNum = 3.0
      let newPredictedDie
      if (ratingNum >= RATING_THRESHOLD) {
        newPredictedDie = idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0]
      } else {
        newPredictedDie =
          idx < DICE_LADDER.length - 1 ? DICE_LADDER[idx + 1] : DICE_LADDER[DICE_LADDER.length - 1]
      }
      setPredictedDie(newPredictedDie)
      setIsRatingView(true)
      suppressPendingAutoOpenRef.current = false

      if (threadId) {
        try {
          const ordersResponse = await readingOrdersApi.getForThread(threadId)
          setReadingOrders(ordersResponse.reading_orders)
        } catch (error) {
          console.error('Failed to fetch reading orders:', error)
          setReadingOrders([])
        }
        try {
          const connectedResponse = await dependenciesApi.getConnectedThreads(threadId)
          setConnectedThreads(connectedResponse.connected_threads)
        } catch (error) {
          console.error('Failed to fetch connected threads:', error)
          setConnectedThreads([])
        }
      } else {
        setReadingOrders([])
        setConnectedThreads([])
      }
    },
    [
      bootstrap,
      currentDie,
      suppressPendingAutoOpenRef,
      setSelectedThreadId,
      setRolledResult,
      setActiveRatingThread,
      setRating,
      setErrorMessage,
      setPredictedDie,
      setIsRatingView,
      setIsActionSheetOpen,
      setIsOverrideOpen,
      setIsDieModalOpen,
    ],
  )

  const handleMigrationComplete = useCallback(
    (migratedThread: Thread) => {
      refetchBootstrap()
      setShowMigrationDialog(false)
      setThreadToMigrate(null)
      enterRatingView(migratedThread.id, null, migratedThread)
    },
    [refetchBootstrap, enterRatingView, setShowMigrationDialog, setThreadToMigrate],
  )

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    if (threadToMigrate) enterRatingView(threadToMigrate.id, null, threadToMigrate)
  }, [enterRatingView, setShowMigrationDialog])

  const handleMigrationClose = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [setShowMigrationDialog, setThreadToMigrate])

  const handleSimpleMigrationComplete = useCallback(
    (issueNumber: string) => {
      // Rating a stale thread moves it out of the stale set, so refresh the stale
      // data (via bootstrap) only when the rated thread was already rendered as
      // stale. This preserves stale indicators without a bootstrap refetch on
      // every rating.
      const wasStale = bootstrap?.stale_thread?.id === activeRatingThread!.id
      setShowSimpleMigration(false)
      rateMutation
        .mutate({
          thread_id: activeRatingThread!.id,
          rating,
          finish_session: false,
          issue_number: issueNumber,
        })
        .then(async (rateResponse) => {
          if (rateResponse && activeRatingThread) {
            setActiveRatingThread({
              ...activeRatingThread,
              issues_remaining: rateResponse.issues_remaining,
              total_issues: rateResponse.total_issues ?? null,
              reading_progress: rateResponse.reading_progress ?? null,
              last_rolled_result: null,
            })
          }
          suppressPendingAutoOpenRef.current = true
          setIsRolling(false)
          setIsRatingView(false)
          setRolledResult(null)
          setSelectedThreadId(null)
          setActiveRatingThread(null)
          setErrorMessage('')
          if (wasStale) {
            await refetchBootstrap()
          }
        })
        .catch((error: unknown) => {
          setErrorMessage(getApiErrorDetail(error))
        })
    },
    [
      activeRatingThread,
      rating,
      rateMutation,
      refetchBootstrap,
      bootstrap,
      setShowSimpleMigration,
      suppressPendingAutoOpenRef,
      setIsRolling,
      setIsRatingView,
      setRolledResult,
      setSelectedThreadId,
      setActiveRatingThread,
      setErrorMessage,
    ],
  )

  function updateRatingUI(val: string) {
    const num = parseFloat(val)
    if (num === RATING_THRESHOLD) navigator.vibrate?.(8)
    setRating(num)
    let newPredictedDie = currentDie
    const idx = DICE_LADDER.indexOf(currentDie)
    if (num >= RATING_THRESHOLD) {
      newPredictedDie = idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0]
    } else {
      newPredictedDie =
        idx < DICE_LADDER.length - 1 ? DICE_LADDER[idx + 1] : DICE_LADDER[DICE_LADDER.length - 1]
    }
    setPredictedDie(newPredictedDie)
  }

  async function handleSubmitRating(finishSession = false) {
    navigator.vibrate?.(20)
    if (rating >= RATING_THRESHOLD) createExplosion()

    const freshTotalIssues =
      bootstrap?.active_thread?.id === activeRatingThread?.id
        ? bootstrap?.active_thread?.total_issues ?? activeRatingThread?.total_issues
        : activeRatingThread?.total_issues

    if (activeRatingThread && freshTotalIssues === null) {
      setShowSimpleMigration(true)
      return
    }

    if (!activeRatingThread) return

    // Capture stale-set membership before the mutation: a rated thread leaves the
    // stale set, so refresh stale data (via bootstrap) only when it was rendered
    // as stale. This avoids a bootstrap round trip on every rating.
    const wasStale = bootstrap?.stale_thread?.id === activeRatingThread.id

    try {
      const rateResponse = await rateMutation.mutate({
        thread_id: activeRatingThread.id,
        rating,
        finish_session: finishSession,
        issue_number: activeRatingThread.issue_number || undefined,
      })

      if (rateResponse) {
        setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: rateResponse.issues_remaining,
          queue_position: rateResponse.queue_position,
          total_issues: rateResponse.total_issues ?? null,
          reading_progress: rateResponse.reading_progress ?? null,
          issue_id: rateResponse.next_unread_issue_id ?? null,
          issue_number: rateResponse.next_unread_issue_number ?? null,
          last_rolled_result: null,
        })
      }

      if (wasStale) {
        try {
          await refetchBootstrap()
        } catch {
          setErrorMessage('Rating saved but failed to refresh. Please refresh the page.')
          return
        }
      }

      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      setErrorMessage('')
      scrollToDice()
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleRefreshThread() {
    try {
      const latest = await refetchBootstrap()
      const refreshedThread = latest?.active_thread

      if (activeRatingThread && refreshedThread?.id === activeRatingThread.id) {
        setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: refreshedThread.issues_remaining ?? 0,
          queue_position: refreshedThread.queue_position ?? activeRatingThread.queue_position,
          total_issues: refreshedThread.total_issues ?? null,
          reading_progress: refreshedThread.reading_progress ?? null,
          issue_id: refreshedThread.issue_id ?? null,
          issue_number: refreshedThread.issue_number ?? null,
          next_issue_id: refreshedThread.next_issue_id ?? null,
          next_issue_number: refreshedThread.next_issue_number ?? null,
          last_rolled_result:
            refreshedThread.last_rolled_result ?? activeRatingThread.last_rolled_result,
        })
      }
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleCancelRating() {
    try {
      await dismissPendingMutation.mutate()
      await refetchBootstrap()
    } catch (error) {
      setErrorMessage(getApiErrorDetail(error))
      return
    }
    setIsRatingView(false)
    setRolledResult(null)
    setSelectedThreadId(null)
    setActiveRatingThread(null)
    setErrorMessage('')
    scrollToDice()
  }

  return {
    readingOrders,
    connectedThreads,
    enterRatingView,
    handleMigrationComplete,
    handleMigrationSkip,
    handleMigrationClose,
    handleSimpleMigrationComplete,
    updateRatingUI,
    handleSubmitRating,
    handleRefreshThread,
    handleCancelRating,
  }
}