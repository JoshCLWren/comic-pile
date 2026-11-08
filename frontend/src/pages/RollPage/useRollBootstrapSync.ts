import { useEffect } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { getApiErrorStatus } from '../../utils/apiError'

interface UseRollBootstrapSyncParams {
  isBootstrapError: boolean
  bootstrapError: unknown
  navigate: NavigateFunction
}

/**
 * Redirects to the login boundary when the session expires. The page owns no
 * refetch here; the selected die is derived during render in `RollPage`
 * from `scopedDieState.die` with fallback to the bootstrap
 * `manual_die`/`current_die` pair (see `selectedDie.ts`), and the rolled
 * result is hydrated by `useRollPendingSession` (wider source
 * `active_thread.last_rolled_result ?? bootstrap.last_rolled_result` when a
 * pending thread exists) with the die/CTA derived from
 * `rolledResult != null`. The scoped `last_roll` spans every session and must
 * never light a stale “rolled” state on a fresh idle die.
 */
export function useRollBootstrapSync({
  isBootstrapError,
  bootstrapError,
  navigate,
}: UseRollBootstrapSyncParams): void {
  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])
}