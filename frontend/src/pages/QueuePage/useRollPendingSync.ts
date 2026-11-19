import { useCallback, useMemo } from 'react'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import type { SessionCurrent } from '../../types'
import type { SessionRefetch } from '../../hooks/useSession'
import { queryClient } from '../../query/queryClient'

interface UseRollPendingSyncParams {
  rollBootstrap: RollBootstrapResponse | null
  session: SessionCurrent | null | undefined
  refetchSession: SessionRefetch
  refetchQueue: () => Promise<void>
}

interface UseRollPendingSyncResult {
  session: SessionCurrent | null | undefined
  onUpdated: () => Promise<void>
  onRefetchSession: () => Promise<void>
}

export function useRollPendingSync({
  rollBootstrap,
  session,
  refetchSession,
  refetchQueue,
}: UseRollPendingSyncParams): UseRollPendingSyncResult {
  const syncedSession = useMemo(() => {
    if (!session) return undefined
    // Bootstrap is authoritative when it exists, including when pending_thread_id is null.
    // Fall back to session.pending_thread_id only when bootstrap data is absent.
    if (rollBootstrap != null) {
      return { ...session, pending_thread_id: rollBootstrap.pending_thread_id }
    }
    return session
  }, [session, rollBootstrap])

  const onUpdated = useCallback(async () => {
    await refetchQueue()
    if (rollBootstrap) {
      await queryClient.refetchQueries({ queryKey: ['roll', 'bootstrap'] })
    }
  }, [refetchQueue, rollBootstrap])

  const onRefetchSession = useCallback(async () => {
    await refetchSession()
    if (rollBootstrap) {
      await queryClient.refetchQueries({ queryKey: ['roll', 'bootstrap'] })
    }
  }, [refetchSession, rollBootstrap])

  return { session: syncedSession, onUpdated, onRefetchSession }
}
