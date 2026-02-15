import { useState, useEffect, useCallback } from 'react'
import { undoApi } from '../services/api'

interface SnapshotData {
  id: number
  timestamp: string
  action: string
}

interface UndoParams {
  sessionId: number
  snapshotId: number
}

export function useSnapshots(sessionId: number | null | undefined) {
  const [data, setData] = useState<SnapshotData[] | null>(null)
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
      .catch(() => {
        if (isActive) setIsError(true)
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

  const mutate = useCallback(async ({ sessionId, snapshotId }: UndoParams) => {
    setIsPending(true)
    setIsError(false)

    try {
      await undoApi.undo(sessionId, snapshotId)
    } catch (error: unknown) {
      setIsError(true)
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to undo action:', err.response?.data?.detail || err.message)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
