import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollSnoozeParams {
  state: RollPageState & RollPageStateSetters
  snoozeMutation: {
    mutate: (expectedPendingThreadId?: number) => Promise<{ correction: { suggest_clarification: boolean; reason_code: string; active_bandwidth: string | null; active_confidence: number | null; predicted_bandwidth: string | null; bandwidth_changed: boolean } | null } | undefined>
  }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<unknown> }
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
}

/**
 * Owns the retained snooze feature. Snoozing from the rating view closes the
 * rating session, while unsnoozing from the pool restores an eligible thread.
 * Both refresh the bounded bootstrap once, keeping the snoozed set truthful
 * without broad refetches. When the backend signals clarification is needed,
 * opens the correction sheet.
 */
export function useRollSnooze({
  state,
  snoozeMutation,
  unsnoozeMutation,
  refetchBootstrap,
}: UseRollSnoozeParams) {
  const {
    setIsRolling,
    setIsRatingView,
    setRolledResult,
    setSelectedThreadId,
    setActiveRatingThread,
    setErrorMessage,
    setShowCorrectionSheet,
    setCorrectionData,
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
      const result = await snoozeMutation.mutate()
      await refetchBootstrap()
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)

      if (result?.correction?.suggest_clarification) {
        setCorrectionData(result.correction)
        setShowCorrectionSheet(true)
      }
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  return { handleUnsnooze, handleSnooze }
}