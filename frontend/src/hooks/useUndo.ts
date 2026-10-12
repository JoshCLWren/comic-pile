import { useEffect, useState, useCallback, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { undoApi } from '../services/api-undo'
import { getApiErrorDetail } from '../utils/apiError'
import { queryKeys } from '../query/queryKeys'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: sessionId != null ? queryKeys.undo.snapshots(sessionId) : [],
    queryFn: () => undoApi.listSnapshots(sessionId!),
    enabled: sessionId != null,
  })

  useEffect(() => {
    if (isError) {
      console.error('Failed to load snapshots:', getApiErrorDetail(error))
    }
  }, [isError, error])

  if (sessionId == null) {
    // SAFETY: no session id means no snapshots; null is the intentional shape when the query is disabled.
    return { data: null as SessionSnapshotsResponse | null, isPending: false, isError: false, refetch }
  }

  // `refetch` is part of the contract because a rating writes a new snapshot:
  // a caller that acts on the newest snapshot must read it again at click time
  // instead of trusting a list that may still be inside its stale window (#3194).
  return { data: data ?? null, isPending, isError, refetch }
}

export function useUndo() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  // Synchronous re-entry guard: React state updates batch, so two rapid
  // clicks can both pass an `isPending` check before either re-renders and
  // each one would log its own identical undo event (#3265).
  const pendingRef = useRef(false)

  const mutate = useCallback(async ({ sessionId, snapshotId }: UndoPayload) => {
    if (pendingRef.current) return
    pendingRef.current = true
    setIsPending(true)
    setIsError(false)

    try {
      await undoApi.undo(sessionId, snapshotId)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to undo action:', getApiErrorDetail(error))
      throw error
    } finally {
      pendingRef.current = false
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
