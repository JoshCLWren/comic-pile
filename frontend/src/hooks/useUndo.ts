import { useState, useEffect, useCallback } from 'react'
import { undoApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const [data, setData] = useState<SessionSnapshotsResponse | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    let isActive = true

    if (!sessionId) {
      setData(null)
      setIsError(false)
      setIsPending(false)
      return
    }

    setIsPending(true)
    setIsError(false)

    undoApi.listSnapshots(sessionId)
      .then((data) => {
        if (isActive) setData(data)
      })
      .catch((error: unknown) => {
        if (isActive) setIsError(true)
        console.error('Failed to load snapshots:', getApiErrorDetail(error))
      })
      .finally(() => {
        if (isActive) setIsPending(false)
      })

    return () => {
      isActive = false
    }
  }, [sessionId])

  return { data, isPending, isError }
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
