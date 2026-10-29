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
  const { setCurrentDie, setRolledResult, setDiceState, setStaleThread, setStaleThreadCount } = state

  // Read the die-mode and last-result projections up front so the sync effect
  // depends on the values it uses rather than on the whole payload identity.
  // `current_die` is already the pinned die while manual mode is active; the
  // explicit `manual_die` preference keeps that contract even if a snapshot
  // ever reports the suspended automatic ladder as `current_die` (#4279).
  const manualDie = bootstrap?.manual_die
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
  }, [manualDie, currentDie, lastRolledResult])

  useEffect(() => {
    const staleFromBootstrap = bootstrap?.stale_thread ?? null
    const count = bootstrap?.stale_thread_count ?? 0
    if (staleFromBootstrap && count > 0) {
      const lastActivity = staleFromBootstrap.last_activity_at
        ? new Date(staleFromBootstrap.last_activity_at)
        : new Date()
      const diffDays = Math.floor((Date.now() - lastActivity.getTime()) / (1000 * 60 * 60 * 24))
      setStaleThread({ ...staleFromBootstrap, days: Math.max(diffDays, 7) })
      setStaleThreadCount(count)
    } else {
      setStaleThread(null)
      setStaleThreadCount(0)
    }
  }, [bootstrap?.stale_thread, bootstrap?.stale_thread_count, setStaleThread, setStaleThreadCount])
}