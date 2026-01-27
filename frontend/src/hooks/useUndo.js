import { useState, useEffect, useCallback } from 'react'
import { undoApi } from '../services/api'

export function useSnapshots(sessionId) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    if (!sessionId) {
      setData(null)
      setIsError(false)
      return
    }

    setIsPending(true)
    setIsError(false)

    undoApi.listSnapshots(sessionId)
      .then(setData)
      .catch(() => setIsError(true))
      .finally(() => setIsPending(false))
  }, [sessionId])

  return { data, isPending, isError }
}

export function useUndo() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ sessionId, snapshotId }) => {
    setIsPending(true)
    setIsError(false)

    try {
      await undoApi.undo(sessionId, snapshotId)
    } catch (error) {
      setIsError(true)
      console.error('Failed to undo action:', error.response?.data?.detail || error.message)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
