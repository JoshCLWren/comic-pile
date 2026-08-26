import { useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { threadsApi } from '../../services/api'
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import type { RollBootstrapResponse, RollBootstrapThread } from '../../types/rollBootstrap'
import type { RollResponse } from '../../types'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'

interface RollMutations {
  setDieMutation: { mutate: (die: number) => Promise<unknown>; isPending: boolean }
  clearManualDieMutation: { mutate: () => Promise<unknown>; isPending: boolean }
  rollMutation: { mutate: () => Promise<RollResponse>; isPending: boolean }
  snoozeMutation: { mutate: (expectedPendingThreadId?: number) => Promise<unknown>; isPending: boolean }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<unknown>; isPending: boolean }
  moveToFrontMutation: { mutate: (id: number) => Promise<unknown>; isPending: boolean }
  moveToBackMutation: { mutate: (id: number) => Promise<unknown>; isPending: boolean }
  shuffleQueueMutation: { mutate: () => Promise<unknown>; isPending: boolean }
}

interface UseRollActionsParams {
  state: RollPageState & RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  rollPool: RollBootstrapThread[]
  navigate: NavigateFunction
  mutations: RollMutations
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  enterRatingView: (
    threadId: number | null,
    result?: number | null,
    metadata?: ThreadMetadata | null,
  ) => Promise<void>
  threadsApi: typeof import('../../services/api').threadsApi
}

/**
 * Owns the retained roll orchestration and thread actions: the timed dice
 * roll, the thread action sheet, stale-read entry, die controls, and the
 * pending-conflict recovery path. Mutations are passed in from the page so
 * this module never creates a second server-state layer.
 */
export function useRollActions({
  state,
  bootstrap,
  rollPool,
  navigate,
  mutations,
  refetchBootstrap,
  enterRatingView,
}: UseRollActionsParams) {
  const {
    isRolling,
    rollIntervalRef,
    rollTimeoutRef,
    suppressPendingAutoOpenRef,
    selectedThread,
    staleThread,
    setSelectedThread,
    setIsActionSheetOpen,
    setIsSetCurrentIssueOpen,
    setErrorMessage,
    setCurrentDie,
    setThreadToMigrate,
    setShowMigrationDialog,
    setIsRolling,
    setDiceState,
  } = state
  const {
    setDieMutation,
    clearManualDieMutation,
    rollMutation,
    snoozeMutation,
    unsnoozeMutation,
    moveToFrontMutation,
    moveToBackMutation,
    shuffleQueueMutation,
  } = mutations

  function handleThreadClick(thread: RollBootstrapThread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

  async function handleReadStale() {
    if (!staleThread) return
    try {
      const response = await threadsApi.setPending(staleThread.id)
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id,
        title: response.title,
        format: response.format,
        issues_remaining: response.issues_remaining,
        queue_position: response.queue_position,
        total_issues: response.total_issues,
        reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id,
        issue_number: response.issue_number,
        next_issue_id: response.next_issue_id,
        next_issue_number: response.next_issue_number,
        last_rolled_result: response.result ?? response.last_rolled_result,
      }
      if (response.total_issues === null) {
        setThreadToMigrate(threadMetadata as RatingThread)
        setShowMigrationDialog(true)
      } else {
        enterRatingView(response.thread_id, response.result, threadMetadata)
      }
    } catch (error) {
      console.error('Failed to set pending thread:', error)
    }
  }

  async function handleShufflePool() {
    try {
      await shuffleQueueMutation.mutate()
      await refetchBootstrap()
    } catch (error) {
      console.error('Shuffle failed:', error)
      console.log(`Blocked thread roll attempt prevented`);
    }
  }

  async function handleAction(action: string) {
    setIsActionSheetOpen(false)
    const isSnoozed =
      bootstrap?.snoozed_threads?.some((t) => t.id === selectedThread!.id) ?? false

    try {
      switch (action) {
        case 'read': {
          const response = await threadsApi.setPending(selectedThread!.id)
          const threadMetadata: ThreadMetadata = {
            id: response.thread_id,
            title: response.title,
            format: response.format,
            issues_remaining: response.issues_remaining,
            queue_position: response.queue_position,
            total_issues: response.total_issues,
            reading_progress: response.reading_progress ?? null,
            issue_id: response.issue_id,
            issue_number: response.issue_number,
            next_issue_id: response.next_issue_id,
            next_issue_number: response.next_issue_number,
            last_rolled_result: response.result ?? response.last_rolled_result,
          }
          if (response.total_issues === null) {
            setThreadToMigrate(threadMetadata as RatingThread)
            setShowMigrationDialog(true)
          } else {
            suppressPendingAutoOpenRef.current = true
            enterRatingView(response.thread_id, response.result, threadMetadata)
          }
          break
        }
        case 'set-current-issue': {
          setIsSetCurrentIssueOpen(true)
          break
        }
        case 'move-front':
          await moveToFrontMutation.mutate(selectedThread!.id)
          await refetchBootstrap()
          break
        case 'move-back':
          await moveToBackMutation.mutate(selectedThread!.id)
          await refetchBootstrap()
          break
        case 'snooze':
          if (isSnoozed) {
            await unsnoozeMutation.mutate(selectedThread!.id)
          } else {
            await snoozeMutation.mutate()
          }
          await refetchBootstrap()
          break
        case 'edit':
          navigate('/queue', { state: { editThreadId: selectedThread!.id } })
          break
      }
    } catch (error) {
      console.error('Action failed:', error)
    }
  }

  async function handleSetDie(die: number) {
    try {
      await setDieMutation.mutate(die)
      setCurrentDie(die)
      return true
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
      return false
    }
  }

  async function handleClearManualDie() {
    try {
      await clearManualDieMutation.mutate()
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function recoverPendingRollConflict() {
    const latest = await refetchBootstrap()
    const pendingId = Number(latest?.pending_thread_id ?? bootstrap?.pending_thread_id ?? 0)
    if (!pendingId) return false
    const pendingMetadata =
      latest?.active_thread && latest.active_thread.id === pendingId
        ? latest.active_thread
        : latest?.roll_pool?.find((thread) => thread.id === pendingId)
    enterRatingView(
      pendingId,
      latest?.last_rolled_result ?? bootstrap?.last_rolled_result ?? null,
      pendingMetadata,
    )
    return true
  }

  function handleRoll() {
    if (isRolling) return
    navigator.vibrate?.(15)
    if (bootstrap?.pending_thread_id && !suppressPendingAutoOpenRef.current) {
      const pendingId = Number(bootstrap.pending_thread_id)
      const pendingMetadata =
        bootstrap?.active_thread && bootstrap.active_thread.id === pendingId
          ? bootstrap.active_thread
          : rollPool.find((thread) => thread.id === pendingId)
      enterRatingView(pendingId, bootstrap?.last_rolled_result ?? null, pendingMetadata)
      return
    }

    if (suppressPendingAutoOpenRef.current && bootstrap?.pending_thread_id) {
      suppressPendingAutoOpenRef.current = false
    }

    if (rollIntervalRef.current) clearInterval(rollIntervalRef.current)
    if (rollTimeoutRef.current) clearTimeout(rollTimeoutRef.current)

    setIsRolling(true)
    setDiceState('idle')

    let currentRollCount = 0
    rollIntervalRef.current = setInterval(() => {
      currentRollCount++
      if (currentRollCount >= 10) {
        clearInterval(rollIntervalRef.current!)
        rollIntervalRef.current = null
        rollTimeoutRef.current = setTimeout(async () => {
          rollTimeoutRef.current = null
          try {
            const response = await rollMutation.mutate()
            enterRatingView(response.thread_id, response.result, response)
            setIsRolling(false)
          } catch (error: unknown) {
            const status = getApiErrorStatus(error)
            const detail = getApiErrorDetail(error)
            if (status === 409) {
              const recovered = await recoverPendingRollConflict()
              if (!recovered) {
                setErrorMessage(
                  detail || 'A roll is already pending. Rate, snooze, or cancel it before rolling again.',
                )
              }
              setIsRolling(false)
              return
            }
            console.error('Roll failed:', error)
            setErrorMessage(detail || 'Failed to roll')
            setIsRolling(false)
          }
        }, 400)
      }
    }, 80)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleRoll()
    }
  }

  useEffect(() => {
    return () => {
      if (rollIntervalRef.current) clearInterval(rollIntervalRef.current)
      if (rollTimeoutRef.current) clearTimeout(rollTimeoutRef.current)
    }
  }, [rollIntervalRef, rollTimeoutRef])

  return {
    handleThreadClick,
    handleReadStale,
    handleShufflePool,
    handleAction,
    handleSetDie,
    handleClearManualDie,
    recoverPendingRollConflict,
    handleRoll,
    handleKeyDown,
  }
}