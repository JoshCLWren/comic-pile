import { useCallback, useEffect } from 'react'
import { useRate } from '../../hooks'
import { threadsApi, readingOrdersApi, dependenciesApi } from '../../services/api'
import { getApiErrorDetail } from '../../utils/apiError'
import { DICE_LADDER, RATING_THRESHOLD, buildRatingThread, createExplosion } from '../utils'
import { useRollPageState, type RollPageStateSetters } from '../useRollPageState'
import type { RatingThread, ThreadMetadata } from '../types'
import type { Thread } from '../../types'

export function useRollRating(setters: RollPageStateSetters, bootstrap: any, refetchBootstrap: () => Promise<any>) {
  const rateMutation = useRate()

  const enterRatingView = useCallback(async (
    threadId: number | null, 
    result: number | null = null, 
    threadMetadata: ThreadMetadata | null = null
  ) => {
    const ratingThread = buildRatingThread(threadId, result, threadMetadata, bootstrap?.active_thread)
    if (!ratingThread) {
      setters.setErrorMessage('Unable to load the selected thread.')
      setters.setIsRatingView(false)
      return
    }

    setters.setIsActionSheetOpen(false)
    setters.setIsOverrideOpen(false)
    setters.setIsDieModalOpen(false)
    setters.setSelectedThreadId(threadId)
    if (result !== null) setters.setRolledResult(result)
    setters.setActiveRatingThread(ratingThread)
    setters.setRating(3.0)
    setters.setErrorMessage('')
    
    const die = setters.currentDie || 6 // Note: currentDie should be passed in or accessed via state
    const idx = DICE_LADDER.indexOf(die)
    setters.setPredictedDie(idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0])
    setters.setIsRatingView(true)
    setters.suppressPendingAutoOpenRef.current = false

    if (threadId) {
      try {
        const ordersResponse = await readingOrdersApi.getForThread(threadId)
        // Reading orders state needs to be handled. 
        // For now, we'll return them or the page will handle them.
        return { readingOrders: ordersResponse.reading_orders }
      } catch (error) {
        console.error('Failed to fetch reading orders:', error)
        return { readingOrders: [] }
      }
    }
    return { readingOrders: [] }
  }, [bootstrap, setters])

  const updateRatingUI = useCallback((val: string, currentDie: number) => {
    const num = parseFloat(val)
    if (num === RATING_THRESHOLD) navigator.vibrate?.(8)
    setters.setRating(num)
    let newPredictedDie = currentDie
    const idx = DICE_LADDER.indexOf(currentDie)
    if (num >= RATING_THRESHOLD) {
      newPredictedDie = idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0]
    } else {
      newPredictedDie = idx < DICE_LADDER.length - 1 ? DICE_LADDER[idx + 1] : DICE_LADDER[DICE_LADDER.length - 1]
    }
    setters.setPredictedDie(newPredictedDie)
  }, [setters])

  const handleSubmitRating = useCallback(async (finishSession = false) => {
    navigator.vibrate?.(20)
    if (setters.rating >= RATING_THRESHOLD) createExplosion()

    const activeRatingThread = setters.activeRatingThread
    if (!activeRatingThread) return

    const freshTotalIssues =
      bootstrap?.active_thread?.id === activeRatingThread.id
        ? bootstrap?.active_thread?.total_issues ?? activeRatingThread.total_issues
        : activeRatingThread.total_issues

    if (freshTotalIssues === null) {
      setters.setShowSimpleMigration(true)
      return
    }

    const wasStale = bootstrap?.stale_thread?.id === activeRatingThread.id

    try {
      const rateResponse = await rateMutation.mutate({
        thread_id: activeRatingThread.id,
        rating: setters.rating,
        finish_session: finishSession,
        issue_number: activeRatingThread.issue_number || undefined,
      })

      if (rateResponse) {
        setters.setActiveRatingThread({
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
          setters.setErrorMessage('Rating saved but failed to refresh. Please refresh the page.')
          return
        }
      }

      setters.setIsRolling(false)
      setters.setIsRatingView(false)
      setters.setRolledResult(null)
      setters.setSelectedThreadId(null)
      setters.setActiveRatingThread(null)
      setters.setErrorMessage('')
    } catch (error: unknown) {
      setters.setErrorMessage(getApiErrorDetail(error))
    }
  }, [bootstrap, rateMutation, refetchBootstrap, setters])

  const handleRefreshThread = useCallback(async () => {
    try {
      const latest = await refetchBootstrap()
      const refreshedThread = latest?.active_thread
      const activeRatingThread = setters.activeRatingThread

      if (activeRatingThread && refreshedThread?.id === activeRatingThread.id) {
        setters.setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: refreshedThread.issues_remaining ?? 0,
          queue_position: refreshedThread.queue_position ?? activeRatingThread.queue_position,
          total_issues: refreshedThread.total_issues ?? null,
          reading_progress: refreshedThread.reading_progress ?? null,
          issue_id: refreshedThread.issue_id ?? null,
          issue_number: refreshedThread.issue_number ?? null,
          next_issue_id: refreshedThread.next_issue_id ?? null,
          next_issue_number: refreshedThread.next_issue_number ?? null,
          last_rolled_result: refreshedThread.last_rolled_result ?? activeRatingThread.last_rolled_result,
        })
      }
    } catch (error: unknown) {
      setters.setErrorMessage(getApiErrorDetail(error))
    }
  }, [refetchBootstrap, setters])

  return {
    enterRatingView,
    updateRatingUI,
    handleSubmitRating,
    handleRefreshThread,
    rateMutation,
  }
}
