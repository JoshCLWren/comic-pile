import { useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { threadsApi } from '../../services/api-threads'
import {
  canSnoozeSeries,
  SNOOZE_REQUIRES_PENDING_SERIES_REASON,
} from '../../components/snoozeAvailability'
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import type { RollBootstrapResponse, RollBootstrapThread } from '../../types/rollBootstrap'
import type { RollResponse } from '../../types'
import type { SnoozeMutationOutcome } from '../../hooks/useSnooze'
import type { SkipMutationOutcome } from '../../hooks/useSkip'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'

interface RollMutations {
  setDieMutation: { mutate: (die: number) => Promise<void>; isPending: boolean }
  clearManualDieMutation: { mutate: () => Promise<void>; isPending: boolean }
  rollMutation: { mutate: () => Promise<RollResponse>; isPending: boolean }
  snoozeMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<SnoozeMutationOutcome>
    isPending: boolean
    retryRefresh?: () => Promise<boolean>
  }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<void>; isPending: boolean }
  skipMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<SkipMutationOutcome>
    isPending: boolean
  }
  unskipMutation: { mutate: (threadId: number) => Promise<void>; isPending: boolean }
  moveToFrontMutation: { mutate: (id: number) => Promise<void>; isPending: boolean }
  moveToBackMutation: { mutate: (id: number) => Promise<void>; isPending: boolean }
  shuffleQueueMutation: { mutate: () => Promise<void>; isPending: boolean }
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
  threadsApi: typeof import('../../services/api-threads').threadsApi
  /**
   * Reports that the committed snooze could not refresh authoritative Roll
   * state. The action sheet has already closed by then, so the page owns the
   * visible recovery surface (a toast with a refresh-only retry).
   */
  onSnoozeRefreshFailed?: (refreshError: unknown) => void
  /**
   * Reports that the committed skip could not refresh authoritative Roll
   * state. The action sheet has already closed by then, so the page owns the
   * visible recovery surface (a toast with a refresh-only retry).
   */
  onSkipRefreshFailed?: (refreshError: unknown) => void
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
  onSnoozeRefreshFailed,
  onSkipRefreshFailed,
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
    setIsShuffleOpen,
    setShuffleError,
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
    skipMutation,
    unskipMutation,
    moveToFrontMutation,
    moveToBackMutation,
    shuffleQueueMutation,
  } = mutations

  function handleThreadClick(thread: RollBootstrapThread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

  async function handleReadStale(threadId: number) {
    const thread = staleThread?.id === threadId ? staleThread : null
    if (!thread) return
    try {
      const response = await threadsApi.setPending(thread.id)
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
        // SAFETY: threadMetadata is assembled from the roll response fields RatingThread requires when total_issues is null.
        setThreadToMigrate(threadMetadata as RatingThread)
        setShowMigrationDialog(true)
      } else {
        enterRatingView(response.thread_id, response.result, threadMetadata)
      }
    } catch (error) {
      console.error('Failed to set pending thread:', error)
    }
  }

  /**
   * Opens the whole-queue shuffle confirmation instead of shuffling. The
   * mutation only runs from `performShuffle`, so one click can never reorder the
   * reader's entire queue on its own (issue #3261).
   */
  function handleShufflePool() {
    setShuffleError('')
    setIsShuffleOpen(true)
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
            // SAFETY: threadMetadata is assembled from the roll response fields RatingThread requires when total_issues is null.
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
        case 'snooze': {
          if (isSnoozed) {
            await unsnoozeMutation.mutate(selectedThread!.id)
            await refetchBootstrap()
            break
          }
          // The snooze endpoint acts on the session's pending thread, so the
          // action sheet may only snooze the series the reader rolled. Firing
          // the request for any other pooled series silently snoozed a
          // different series — or failed with a 400 that this handler used to
          // swallow into the console after the sheet had already closed, so the
          // click looked successful and nothing was recorded (#3260).
          if (!canSnoozeSeries({
            threadId: selectedThread!.id,
            isSnoozed,
            pendingThreadId: bootstrap?.pending_thread_id,
          })) {
            setErrorMessage(SNOOZE_REQUIRES_PENDING_SERIES_REASON)
            break
          }
          // The id doubles as `expectedPendingThreadId`, which is what lets the
          // snooze hook recover an auth failure and reconcile an ambiguous one.
          // The mutation owns the single authoritative refresh; this handler
          // only reports its outcome so a stale pool is never silent.
          const outcome = await snoozeMutation.mutate(selectedThread!.id)
          if (!outcome.refreshed) {
            if (onSnoozeRefreshFailed) {
              onSnoozeRefreshFailed(outcome.refreshError)
            } else {
              setErrorMessage(getApiErrorDetail(outcome.refreshError))
            }
          }
          break
        }
        case 'skip': {
          const isSkipped =
            bootstrap?.skipped_thread_ids?.includes(selectedThread!.id) ?? false
          if (isSkipped) {
            // Unskip does not reconcile bootstrap state in its hook, so this
            // one explicit refresh is what drops the skipped membership.
            await unskipMutation.mutate(selectedThread!.id)
            await refetchBootstrap()
            break
          }
          // The skip mutation owns the single authoritative refresh. This
          // handler only reports an exhausted refresh so a stale pool is never
          // silent; it must not start a second request.
          const outcome = await skipMutation.mutate(bootstrap?.pending_thread_id ?? undefined)
          if (!outcome.refreshed) {
            if (onSkipRefreshFailed) {
              onSkipRefreshFailed(outcome.refreshError)
            } else {
              setErrorMessage(getApiErrorDetail(outcome.refreshError))
            }
          }
          break
        }
        case 'edit':
          navigate(`/thread/${selectedThread!.id}`, { state: { openEditModal: true } })
          break
      }
    } catch (error) {
      console.error('Action failed:', error)
      // The sheet already closed by this point, so a console-only failure left
      // the reader believing a no-op action had worked. Surface the reason
      // instead (#3260).
      setErrorMessage(getApiErrorDetail(error))
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

  /**
   * Runs the confirmed whole-queue shuffle. The confirmation only closes once
   * the mutation succeeds, so a failure leaves the dialog in place and the
   * reader can retry without re-discovering the button. The reason renders
   * inside the dialog: a toast paints below the modal layer, and a native
   * `alert` blocks the page and is invisible to QA automation (issue #4193).
   */
  async function performShuffle() {
    try {
      await shuffleQueueMutation.mutate()
      await refetchBootstrap()
      setShuffleError('')
      setIsShuffleOpen(false)
    } catch (error) {
      console.error('Shuffle failed:', error)
      setShuffleError(`Failed to shuffle pool: ${getApiErrorDetail(error)}`)
    }
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
    performShuffle,
    handleAction,
    handleSetDie,
    handleClearManualDie,
    recoverPendingRollConflict,
    handleRoll,
    handleKeyDown,
  }
}