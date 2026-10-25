import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { SkipMutationOutcome } from '../../hooks/useSkip'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'
import type { ThreadMetadata } from './types'

interface UseRollSkipParams {
  state: RollPageState & RollPageStateSetters
  skipMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<SkipMutationOutcome>
    hasRefreshError?: boolean
    refreshError?: unknown
    retryRefresh?: () => Promise<boolean>
  }
  unskipMutation: { mutate: (threadId: number) => Promise<void> }
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  enterRatingView: (
    threadId: number | null,
    result?: number | null,
    metadata?: ThreadMetadata | null,
  ) => Promise<void>
  /** Pending series the skip request expects to consume. */
  expectedPendingThreadId?: number
  /**
   * Reports that the committed skip could not refresh authoritative Roll
   * state. The action sheet has already closed by then, so the page owns the
   * visible recovery surface (a toast with a refresh-only retry).
   */
  onRefreshFailed?: (refreshError: unknown) => void
}

/**
 * Owns the retained skip feature. The successful skip mutation is the single
 * owner of the authoritative bootstrap refresh, so this hook never issues a
 * second network refresh for the same success: it enters the next rating view
 * from the mutation response while the published bootstrap snapshot supplies
 * the pool, pending membership, and session history.
 *
 * Unskip is different: `useUnskip` does not reconcile bootstrap state, so the
 * unskip path keeps exactly one explicit refresh. Skipped membership is never
 * served from a pre-unskip snapshot.
 */
export function useRollSkip({
  state,
  skipMutation,
  unskipMutation,
  refetchBootstrap,
  enterRatingView,
  expectedPendingThreadId,
  onRefreshFailed,
}: UseRollSkipParams) {
  const {
    suppressPendingAutoOpenRef,
    setRolledResult,
    setErrorMessage,
  } = state

  function reportRefreshFailure(outcome: SkipMutationOutcome) {
    if (outcome.refreshed) return
    if (onRefreshFailed) {
      onRefreshFailed(outcome.refreshError)
    } else {
      setErrorMessage(getApiErrorDetail(outcome.refreshError))
    }
  }

  async function handleSkip() {
    try {
      const outcome = await skipMutation.mutate(expectedPendingThreadId)
      if (!outcome.response) {
        // An ambiguous skip that reconciled as committed already published the
        // authoritative snapshot; there is no new roll response to rate.
        reportRefreshFailure(outcome)
        return
      }

      const response = outcome.response
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id,
        title: response.title,
        format: response.format,
        issues_remaining: response.issues_remaining,
        queue_position: response.queue_position,
        total_issues: response.total_issues ?? null,
        reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id ?? null,
        issue_number: response.issue_number ?? null,
        next_issue_id: response.next_issue_id ?? null,
        next_issue_number: response.next_issue_number ?? null,
        last_rolled_result: response.result ?? null,
      }
      suppressPendingAutoOpenRef.current = true
      await enterRatingView(response.thread_id, response.result ?? null, threadMetadata)
      setRolledResult(response.result ?? null)
      reportRefreshFailure(outcome)
    } catch (error) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleUnskip(threadId: number) {
    try {
      await unskipMutation.mutate(threadId)
      // Unlike skip, unskip does not reconcile bootstrap state in its hook, so
      // this one explicit refresh is required to drop the skipped membership.
      await refetchBootstrap()
    } catch (error) {
      console.error('Unskip failed:', error)
    }
  }

  return {
    handleSkip,
    handleUnskip,
    retryRefresh: skipMutation.retryRefresh,
    hasRefreshError: skipMutation.hasRefreshError ?? false,
    refreshError: skipMutation.refreshError,
  }
}
