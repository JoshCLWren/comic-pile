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
 *
 * Die selection (#4352): the selected die is derived during render in
 * `RollPage` from `scopedDieState.die` with fallback to the bootstrap
 * `manual_die`/`current_die` pair, so this hook no longer syncs it via
 * effect/state. The last-roll projection stays bootstrap-only: bootstrap
 * reports the current session's pending roll, while the scoped `last_roll`
 * spans every session, so preferring it would light a stale “rolled” state
 * on a fresh idle die.
 */
export function useRollBootstrapSync({
  state,
  bootstrap,
  isBootstrapError,
  bootstrapError,
  navigate,
}: UseRollBootstrapSyncParams): void {
  const { setRolledResult, setDiceState } = state

  const lastRolledResult = bootstrap?.last_rolled_result

  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])

  useEffect(() => {
    if (lastRolledResult !== undefined && lastRolledResult !== null) {
      setRolledResult(lastRolledResult)
      setDiceState('rolled')
    }
  }, [lastRolledResult, setRolledResult, setDiceState])
}