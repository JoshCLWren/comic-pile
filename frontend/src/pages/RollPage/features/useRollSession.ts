import { useCallback, useEffect } from 'react'
import {
  useRollBootstrap,
} from '../../hooks/useRollBootstrap'
import {
  useClearManualDie,
  useRoll,
  useSetDie,
} from '../../hooks/useRoll'
import { getApiErrorDetail } from '../../utils/apiError'
import { DICE_LADDER } from '../../components/diceLadder'
import type { RollPageStateSetters } from '../useRollPageState'

export function useRollSession(setters: RollPageStateSetters) {
  const {
    data: bootstrap,
    refetch: refetchBootstrap,
    isPending: isBootstrapLoading,
    isError: isBootstrapError,
    error: bootstrapError,
  } = useRollBootstrap()

  const setDieMutation = useSetDie()
  const clearManualDieMutation = useClearManualDie()
  const rollMutation = useRoll()

  const handleSetDie = useCallback(async (die: number) => {
    try {
      await setDieMutation.mutate(die)
      setters.setCurrentDie(die)
      return true
    } catch (error: unknown) {
      setters.setErrorMessage(getApiErrorDetail(error))
      return false
    }
  }, [setDieMutation, setters])

  const handleClearManualDie = useCallback(async () => {
    try {
      await clearManualDieMutation.mutate()
    } catch (error: unknown) {
      setters.setErrorMessage(getApiErrorDetail(error))
    }
  }, [clearManualDieMutation, setters])

  const recoverPendingRollConflict = useCallback(async () => {
    const latest = await refetchBootstrap()
    const pendingId = Number(latest?.pending_thread_id ?? bootstrap?.pending_thread_id ?? 0)
    if (!pendingId) return false
    
    // This part requires enterRatingView which is in useRollRating
    // We will handle the actual transition in the page or via a callback
    return {
      pendingId,
      lastRolledResult: latest?.last_rolled_result ?? bootstrap?.last_rolled_result ?? null,
      pendingMetadata: latest?.active_thread && latest.active_thread.id === pendingId
        ? latest.active_thread 
        : latest?.roll_pool?.find((thread) => thread.id === pendingId),
    }
  }, [refetchBootstrap, bootstrap])

  useEffect(() => {
    if (bootstrap?.current_die) setters.setCurrentDie(bootstrap.current_die)
    if (bootstrap?.last_rolled_result !== undefined && bootstrap?.last_rolled_result !== null) {
      setters.setRolledResult(bootstrap.last_rolled_result)
    }
  }, [bootstrap?.current_die, bootstrap?.last_rolled_result, setters])

  return {
    bootstrap,
    refetchBootstrap,
    isBootstrapLoading,
    isBootstrapError,
    bootstrapError,
    handleSetDie,
    handleClearManualDie,
    recoverPendingRollConflict,
    setDieMutation,
    clearManualDieMutation,
    rollMutation,
  }
}
