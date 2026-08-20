import { getApiErrorDetail } from '../../utils/apiError'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from './useRollPageState'

interface UseRollSnoozeParams {
  state: RollPageState & RollPageStateSetters
  snoozeMutation: { mutate: (expectedPendingThreadId?: number) => Promise<unknown> }
  unsnoozeMutation: { mutate: (threadId: number) => Promise<unknown> }
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>
  scrollToDice: () => void
}

/**
 * Owns the retained snooze feature. Snoozing from the rating view closes the
 * rating session, while unsnoozing from the pool restores an eligible thread.
 * Both refresh the bounded bootstrap once, keeping the snoozed set truthful
 * without broad refetches.
 */
export function useRollSnooze({
  state,
  snoozeMutation,
  unsnoozeMutation,
  refetchBootstrap,
  scrollToDice,
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
      await snoozeMutation.mutate()
      await refetchBootstrap()
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      scrollToDice()
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  return { handleUnsnooze, handleSnooze }
}