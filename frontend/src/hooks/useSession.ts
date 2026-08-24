import { useCallback, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { sessionApi } from '../services/api'
import type {
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
} from '../types'
import { useToast } from '../contexts/useToast'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id'

export function useSession() {
  const { showToast } = useToast()
  const lastNotifiedSessionIdRef = useRef<number | null>(null)

  const query = useQuery({
    queryKey: queryKeys.session.current(),
    queryFn: async () => {
      const result = await sessionApi.getCurrent()

      const currentSessionId = result.id
      const currentUserId = result.user_id ?? 'anonymous'
      const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`
      let storedSessionId: string | null = null
      try {
        storedSessionId = localStorage.getItem(storageKey)
      } catch {
        // Session loading should still succeed when browser storage is unavailable.
      }
      let previousSessionId: number | null = null
      if (storedSessionId) {
        const parsed = parseInt(storedSessionId, 10)
        previousSessionId = Number.isFinite(parsed) ? parsed : null
      }

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
        // Persisting the session ID is best effort and must not hide the API result.
      }
      return result
    },
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
    refetch: query.refetch,
  }
}

export function useSessions() {
  const query = useQuery({
    queryKey: queryKeys.session.pages(),
    queryFn: async () => {
      const result: SessionListResponse = await sessionApi.list({}, null)
      return result
    },
    staleTime: 30_000,
    retry: false,
  })

  const loadMoreMutation = useMutation({
    mutationFn: async (pageToken: string) => {
      return sessionApi.list({}, pageToken)
    },
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.session.pages(), (old: SessionListResponse | undefined) => {
        if (!old) return result
        const existingIds = new Set(old.sessions.map((s) => s.id))
        const newSessions = result.sessions.filter((s) => !existingIds.has(s.id))
        return {
          ...result,
          sessions: [...old.sessions, ...newSessions],
        }
      })
    },
  })

  const data = query.data?.sessions ?? []
  const nextPageToken = query.data?.next_page_token ?? null
  const hasMore = nextPageToken !== null && data.length > 0

  const loadMore = useCallback(async () => {
    if (!nextPageToken || loadMoreMutation.isPending) return
    await loadMoreMutation.mutateAsync(nextPageToken)
  }, [nextPageToken, loadMoreMutation])

  return {
    data,
    isPending: query.isLoading,
    isLoadingMore: loadMoreMutation.isPending,
    isError: query.isError,
    error: query.error ?? null,
    hasMore,
    loadMore,
    refetch: query.refetch,
  }
}

export function useSessionDetails(id: number | string | null | undefined) {
  const enabled = id != null

  const query = useQuery({
    queryKey: queryKeys.session.detail(Number(id ?? -1)),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No session ID')
      }
      return sessionApi.getDetails(id)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
    refetch: query.refetch,
  }
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const enabled = id != null

  const query = useQuery({
    queryKey: queryKeys.session.snapshots(id ?? ''),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No session ID')
      }
      return sessionApi.getSnapshots(id)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
    refetch: query.refetch,
  }
}

export function useRestoreSessionStart() {
  const mutation = useMutation({
    mutationFn: (sessionId: number | string) => sessionApi.restoreSessionStart(sessionId),
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        console.error(
          'Failed to restore session:',
          err.response?.data?.detail || err.message,
        )
      } else {
        console.error('Failed to restore session:', err instanceof Error ? err.message : String(err))
      }
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error ?? null,
  }
}
