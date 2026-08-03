import { useCallback, useEffect, useRef, type SetStateAction } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToast } from '../contexts/useToast'
import { queryKeys } from '../query/queryKeys'
import { sessionApi } from '../services/api'
import type { SessionCurrent } from '../types'

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id'

/**
 * Load current-session state through the canonical TanStack query key.
 *
 * Rating, snooze, and Queue mutations invalidate this exact key, so consumers
 * using this hook receive one shared refresh instead of maintaining isolated
 * request state that cannot observe centralized cache effects.
 */
export function useCurrentSessionQuery() {
  const client = useQueryClient()
  const { showToast } = useToast()
  const lastNotifiedSessionIdRef = useRef<number | null>(null)
  const key = queryKeys.session.current()

  const query = useQuery({
    queryKey: key,
    queryFn: () => sessionApi.getCurrent(),
  })

  useEffect(() => {
    const session = query.data
    if (!session) return

    const currentSessionId = session.id
    const currentUserId = session.user_id ?? 'anonymous'
    const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`
    let storedSessionId: string | null = null

    try {
      storedSessionId = localStorage.getItem(storageKey)
    } catch {
      // Session loading must still succeed when browser storage is unavailable.
    }

    const parsedSessionId = storedSessionId
      ? Number.parseInt(storedSessionId, 10)
      : Number.NaN
    const previousSessionId = Number.isFinite(parsedSessionId)
      ? parsedSessionId
      : null

    if (
      previousSessionId !== null &&
      currentSessionId !== previousSessionId &&
      currentSessionId !== lastNotifiedSessionIdRef.current
    ) {
      showToast('Session started. Happy reading!', 'info')
      lastNotifiedSessionIdRef.current = currentSessionId
    }

    try {
      localStorage.setItem(storageKey, currentSessionId.toString())
    } catch {
      // Persisting the session ID is best effort and must not hide API data.
    }
  }, [query.data, showToast])

  const setData = useCallback(
    (value: SetStateAction<SessionCurrent | null>) => {
      client.setQueryData<SessionCurrent | null>(key, (current) =>
        typeof value === 'function' ? value(current ?? null) : value,
      )
    },
    [client, key],
  )

  return {
    ...query,
    data: query.data ?? null,
    setData,
  }
}
