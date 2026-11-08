import { useEffect } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import type { DieStateResponse } from '../../generated/nativeV2Client'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import { getApiErrorStatus } from '../../utils/apiError'
import type { RollPageStateSetters } from './useRollPageState'

interface UseRollBootstrapSyncParams {
  state: RollPageStateSetters
  bootstrap?: RollBootstrapResponse | null
  scopedDieState?: DieStateResponse | null
  isBootstrapError: boolean
  bootstrapError: unknown
  navigate: NavigateFunction
}

/**
 * Keeps Roll page state derived from the bounded bootstrap payload in sync
 * with the server response, and redirects to the login boundary when the
 * session expires. The page owns no refetch here; this module only projects
 * the bootstrap response onto focused Roll feature state.
 *
 * Die surface migration (#4719): the scoped die-state resource is
 * authoritative for the current die, so the projection prefers
 * `scopedDieState.die` and falls back to the bootstrap
 * `manual_die`/`current_die` pair only while the scoped query is
 * unsettled or has failed. The last-roll projection stays bootstrap-only:
 * bootstrap reports the current session's pending roll, while the scoped
 * `last_roll` spans every session, so preferring it would light a stale
 * “rolled” state on a fresh idle die.
 */
export function useRollBootstrapSync({
  state,
  bootstrap,
  scopedDieState,
  isBootstrapError,
  bootstrapError,
  navigate,
}: UseRollBootstrapSyncParams): void {
  const { setCurrentDie, setRolledResult, setDiceState } = state

  const manualDie = bootstrap?.manual_die ?? null
  const currentDie = bootstrap?.current_die
  const lastRolledResult = bootstrap?.last_rolled_result
  const scopedDie = scopedDieState?.die ?? undefined

  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])

  useEffect(() => {
    const effectiveDie = scopedDie ?? manualDie ?? currentDie
    if (effectiveDie) setCurrentDie(effectiveDie)
    if (lastRolledResult !== undefined && lastRolledResult !== null) {
      setRolledResult(lastRolledResult)
      setDiceState('rolled')
    }
  }, [scopedDie, manualDie, currentDie, lastRolledResult, setCurrentDie, setRolledResult, setDiceState])
}