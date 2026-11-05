import { useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { threadsApi } from '../../services/api-threads'
import { queryClient } from '../../query/queryClient'
import { queryKeys } from '../../query/queryKeys'
import {
  canSnoozeSeries,
  SNOOZE_REQUIRES_PENDING_SERIES_REASON,
} from '../../components/snoozeAvailability'
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import type { RollBootstrapResponse, RollBootstrapThread } from '../../types/rollBootstrap'
import type { RollResponse } from '../../types'
import type { SnoozeMutationOutcome } from '../../hooks/useSnooze'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'

interface RollMutations {
  setDieMutation: { mutate: (die: number) => Promise<void>; isPending: boolean }
  rollMutation: { mutate: () => Promise<RollResponse>; isPending: boolean }
  snoozeMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<SnoozeMutationOutcome>
    isPending: boolean
    retryRefresh?: () => Promise<boolean>
  }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<void>; isPending: boolean }
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
}

/**
 * Owns the retained roll orchestration and thread actions: the timed dice
 * roll, the thread action sheet, die controls, and the pending-conflict
 * recovery path. Mutations are passed in from the page so this module never
 * creates a second server-state layer.
 */
/**
 * True when the mutation-owned bootstrap refresh (issued by the move/shuffle
 * hook's queue-movement invalidation) settled into an error. Reading the
 * already-run refresh's state costs no network request, so the single-refresh
 * contract keeps its feedback: a committed move/shuffle whose pool refresh
 * failed is reported the same way the snooze hook reports an exhausted
 * refresh (#4276), instead of the retired duplicate `refetchBootstrap()` whose
 * rejection used to surface through the action catch.
 */
function bootstrapRefreshSettledErrored(): boolean {
  const state = queryClient.getQueryState(queryKeys.roll.bootstrap())
  return (state?.error ?? null) != null
}

const POOL_REFRESH_FAILED_REASON = 'the Roll pool did not refresh. Refresh the page to see the new order.'

export function useRollActions({
  state,
  bootstrap,
  rollPool,
  navigate,
  mutations,
  refetchBootstrap,
  enterRatingView,
  onSnoozeRefreshFailed,
}: UseRollActionsParams) {
  const {
    isRolling,
    rollIntervalRef,
    rollTimeoutRef,
    suppressPendingAutoOpenRef,
    selectedThread,
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
          // The useMoveToFront hook already invalidates the retained roll
          // bootstrap, and the bootstrap query is active here, so the mutation
          // settles with one authoritative refresh. An explicit `refetch()`
          // after the invalidation sent the bootstrap endpoint a second,
          // identical refresh (re-ran the in-flight session POST too).
          await moveToFrontMutation.mutate(selectedThread!.id)
          if (bootstrapRefreshSettledErrored()) {
            setErrorMessage(`Moved ${selectedThread!.title}, but ${POOL_REFRESH_FAILED_REASON}`)
          }
          break
        case 'move-back':
          // Same single-refresh ownership as `move-front` above: the move hook
          // owns the queue-movement invalidation pass; no caller refresh.
          await moveToBackMutation.mutate(selectedThread!.id)
          if (bootstrapRefreshSettledErrored()) {
            setErrorMessage(`Moved ${selectedThread!.title}, but ${POOL_REFRESH_FAILED_REASON}`)
          }
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
      // `useShuffleQueue` invalidates the retained roll bootstrap and the
      // query is active here, so the mutation settles with one authoritative
      // refresh; this handler must not issue a second one. A pool refresh
      // that failed inside that pass is reported here (no extra request) the
      // same way the snooze hook reports an exhausted refresh (#4276).
      await shuffleQueueMutation.mutate()
      if (bootstrapRefreshSettledErrored()) {
        setShuffleError(`Shuffled, but ${POOL_REFRESH_FAILED_REASON}`)
        return
      }
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
    handleShufflePool,
    performShuffle,
    handleAction,
    handleSetDie,
    recoverPendingRollConflict,
    handleRoll,
    handleKeyDown,
  }
}