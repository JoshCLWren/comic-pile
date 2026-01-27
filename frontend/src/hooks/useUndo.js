import { useState, useEffect, useCallback } from 'react'
import { undoApi } from '../services/api'

export function useSnapshots(sessionId) {
  const [data, setData] = useState(null)
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
