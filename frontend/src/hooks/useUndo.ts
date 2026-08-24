import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { undoApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'
import { queryKeys } from '../query/queryKeys'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const enabled = sessionId != null

  const query = useQuery({
    queryKey: queryKeys.undo.snapshots(sessionId ?? ''),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No session ID')
      }
      return undoApi.listSnapshots(sessionId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
  }
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
