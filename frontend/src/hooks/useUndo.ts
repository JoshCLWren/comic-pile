import { useEffect, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { undoApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import { queryKeys } from '../query/queryKeys'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: sessionId != null ? queryKeys.undo.snapshots(sessionId) : [],
    queryFn: () => undoApi.listSnapshots(sessionId!),
    enabled: sessionId != null,
    initialData: null as SessionSnapshotsResponse | null,
  })

  useEffect(() => {
    if (isError) {
      console.error('Failed to load snapshots:', getApiErrorDetail(error))
    }
  }, [isError, error])

  if (sessionId == null) {
    return { data: null as SessionSnapshotsResponse | null, isPending: false, isError: false }
  }

  return { data: data ?? null, isPending, isError }
}

export function useUndo() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ sessionId, snapshotId }: UndoPayload) => {
    setIsPending(true)
    setIsError(false)

    try {
      await undoApi.undo(sessionId, snapshotId)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to undo action:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
