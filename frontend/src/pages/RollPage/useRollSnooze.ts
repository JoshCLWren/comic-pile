import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { SnoozeCorrectionInfo } from '../../types'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollSnoozeParams {
  state: RollPageState & RollPageStateSetters
  snoozeMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<{ correction?: SnoozeCorrectionInfo | null } | undefined>
  }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<unknown> }
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  onClarificationSuggested?: (correction: SnoozeCorrectionInfo) => void
}

/**
 * Owns the retained snooze feature. Snoozing from the rating view closes the
 * rating session, while unsnoozing from the pool restores an eligible thread.
 * Both refresh the bounded bootstrap once, keeping the snoozed set truthful
 * without broad refetches. When the backend flags a repeated/contradictory
 * mismatch (`suggest_clarification`) the flow surfaces that correction so the
 * page can offer the reading-mode quiz without forcing it.
 */
export function useRollSnooze({
  state,
  snoozeMutation,
  unsnoozeMutation,
  refetchBootstrap,
  onClarificationSuggested,
}: UseRollSnoozeParams) {
  const {
    setIsRolling,
    setIsRatingView,
    setRolledResult,
    setSelectedThreadId,
    setActiveRatingThread,
    setErrorMessage,
  } = state

  async function handleUnsnooze(threadId: number) {
    try {
      await unsnoozeMutation.mutate(threadId)
      await refetchBootstrap()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }

  async function handleSnooze() {
    try {
      const response = await snoozeMutation.mutate()
      await refetchBootstrap()
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      const correction = response?.correction
      if (correction?.suggest_clarification) {
        onClarificationSuggested?.(correction)
      }
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  return { handleUnsnooze, handleSnooze }
}