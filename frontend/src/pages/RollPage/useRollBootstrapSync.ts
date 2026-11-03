import { useEffect } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import { getApiErrorStatus } from '../../utils/apiError'
import type { RollPageStateSetters } from './useRollPageState'

interface UseRollBootstrapSyncParams {
  state: RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  isBootstrapError: boolean
  bootstrapError: unknown
  navigate: NavigateFunction
}

/**
 * Keeps Roll page state derived from the bounded bootstrap payload in sync
 * with the server response, and redirects to the login boundary when the
 * session expires. The page owns no refetch here; this module only projects
 * the bootstrap response onto focused Roll feature state.
 */
export function useRollBootstrapSync({
  state,
  bootstrap,
  isBootstrapError,
  bootstrapError,
  navigate,
}: UseRollBootstrapSyncParams): void {
  const { setCurrentDie, setRolledResult, setDiceState } = state

  const manualDie = bootstrap?.manual_die ?? null
  const currentDie = bootstrap?.current_die
  const lastRolledResult = bootstrap?.last_rolled_result

  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])

  useEffect(() => {
    const effectiveDie = manualDie ?? currentDie
    if (effectiveDie) setCurrentDie(effectiveDie)
    if (lastRolledResult !== undefined && lastRolledResult !== null) {
      setRolledResult(lastRolledResult)
      setDiceState('rolled')
    }
  }, [manualDie, currentDie, lastRolledResult, setCurrentDie, setRolledResult, setDiceState])
}