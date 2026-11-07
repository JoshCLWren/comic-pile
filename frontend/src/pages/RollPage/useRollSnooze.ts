import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollResponse } from '../../types'
import type { ThreadMetadata } from './types'
import type { SnoozeMutationOutcome } from '../../hooks/useSnooze'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import { removeRollSnooze } from '../../services/api-roll'

interface UseRollSnoozeParams {
  state: RollPageState & RollPageStateSetters
  snoozeMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<SnoozeMutationOutcome>
    hasRefreshError?: boolean
    refreshError?: unknown
    retryRefresh?: () => Promise<boolean>
  }
  rerollMutation?: { mutate: () => Promise<RollResponse> }
  enterRatingView?: (
    threadId: number | null,
    result?: number | null,
    threadMetadata?: ThreadMetadata | null,
  ) => Promise<void>
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  /**
   * Reports that the committed snooze could not refresh authoritative Roll
   * state. The page owns a visible recovery surface (a toast with a
   * refresh-only retry), because the rating view moves to the replacement
   * offer and can no longer reliably show a pool-stale error line.
   */
  onRefreshFailed?: (refreshError: unknown) => void
}

/**
 * Owns the retained snooze feature. Snoozing from the rating view moves the
 * session to the replacement offer the Rust writer selected atomically, while
 * unsnoozing from the pool restores an eligible thread.
 * The successful snooze mutation is the single owner of the authoritative
 * bootstrap refresh, so this hook never issues a second network refresh for the
 * same success.
 */
export function useRollSnooze({
  state,
  snoozeMutation,
  rerollMutation,
  enterRatingView,
  refetchBootstrap,
  onRefreshFailed,
}: UseRollSnoozeParams) {
  const {
    suppressPendingAutoOpenRef,
    setIsRolling,
    setIsRatingView,
    setRolledResult,
    setSelectedThreadId,
    setActiveRatingThread,
    setErrorMessage,
  } = state

  /**
   * Removes a thread from the browser snooze cookie and refreshes the bootstrap
   * to update the UI state.
   */
  async function handleUnsnooze(threadId: number) {
    try {
      // Roll unsnooze is client-only: remove the thread from the browser snooze cookie
      removeRollSnooze(threadId)
      await refetchBootstrap()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }

  /**
   * One Roll/Reroll action from the rating view: the Rust offer records the
   * pending snooze and selects the next offer in a single command. The
   * refreshed bootstrap rehydrates the next rating view.
   */
  async function handleReroll() {
    if (!rerollMutation) return
    try {
      const response = await rerollMutation.mutate()
      if (enterRatingView) {
        // Use the offer response directly so a failed background refresh cannot
        // leave the just-snoozed thread open in the rating view.
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
          last_rolled_result: response.result,
        }
        await enterRatingView(response.thread_id, response.result, threadMetadata)
      } else {
        await refetchBootstrap()
        setIsRolling(false)
        setIsRatingView(false)
        setRolledResult(null)
        setSelectedThreadId(null)
        setActiveRatingThread(null)
      }
      setErrorMessage('')
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleSnooze() {
    try {
      const expectedId = state.activeRatingThread?.id
      const outcome = await snoozeMutation.mutate(expectedId)
      setIsRolling(false)
      if (enterRatingView && outcome.response?.thread_id != null) {
        // The Rust offer recorded the snooze and selected a replacement in the
        // same transaction (#4589). Keep the rating view open for it instead
        // of silently closing a pending session.
        const threadMetadata: ThreadMetadata = {
          id: outcome.response.thread_id,
          title: outcome.response.title,
          format: outcome.response.format,
          issues_remaining: outcome.response.issues_remaining,
          queue_position: outcome.response.queue_position,
          total_issues: outcome.response.total_issues,
          reading_progress: outcome.response.reading_progress ?? null,
          issue_id: outcome.response.issue_id,
          issue_number: outcome.response.issue_number,
          next_issue_id: outcome.response.next_issue_id,
          next_issue_number: outcome.response.next_issue_number,
          last_rolled_result: outcome.response.result,
        }
        await enterRatingView(outcome.response.thread_id, outcome.response.result, threadMetadata)
        if (!outcome.refreshed) {
          // The bootstrap still names the snoozed thread as pending.
          // Suppress pending auto-open so stale data cannot restore the
          // old pending thread over the replacement just entered.
          suppressPendingAutoOpenRef.current = true
        }
      } else {
        setIsRatingView(false)
        setRolledResult(null)
        setSelectedThreadId(null)
        setActiveRatingThread(null)
      }
      // The mutation already published authoritative state when its bounded
      // refresh succeeded. When it exhausted those attempts the reader would
      // otherwise be looking at a closed rating view over a stale pool, so the
      // failure is surfaced with a refresh-only retry instead of a second
      // network refresh from this caller.
      if (!outcome.refreshed) {
        if (onRefreshFailed) {
          onRefreshFailed(outcome.refreshError)
        } else {
          setErrorMessage(getApiErrorDetail(outcome.refreshError))
        }
      }
    } catch (error: unknown) {
      const errorDetail = getApiErrorDetail(error)
      if (errorDetail.includes('No pending thread to snooze')) {
        // Bounded reconciliation: if backend says no pending thread,
        // the current rating view is stale. Clear it.
        setIsRolling(false)
        setIsRatingView(false)
        setRolledResult(null)
        setSelectedThreadId(null)
        setActiveRatingThread(null)
      } else {
        setErrorMessage(errorDetail)
      }
    }
  }

  return {
    handleUnsnooze,
    handleSnooze,
    handleReroll,
    retryRefresh: snoozeMutation.retryRefresh,
    hasRefreshError: snoozeMutation.hasRefreshError ?? false,
    refreshError: snoozeMutation.refreshError,
  }
}
