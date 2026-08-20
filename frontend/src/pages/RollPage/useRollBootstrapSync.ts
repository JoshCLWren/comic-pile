import { useEffect } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import { getApiErrorStatus } from '../../utils/apiError'
import type { RollPageStateSetters } from './useRollPageState'

interface UseRollBootstrapSyncParams {
  state: RollPageStateSetters
  bootstrap?: RollBootstrapResponse
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
  const { setCurrentDie, setRolledResult, setStaleThread, setStaleThreadCount } = state

  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])

  useEffect(() => {
    if (bootstrap?.current_die) setCurrentDie(bootstrap.current_die)
    if (bootstrap?.last_rolled_result !== undefined && bootstrap?.last_rolled_result !== null) {
      setRolledResult(bootstrap.last_rolled_result)
    }
  }, [bootstrap?.current_die, bootstrap?.last_rolled_result, setCurrentDie, setRolledResult])

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