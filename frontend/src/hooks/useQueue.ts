import { useCallback, useState } from 'react'
import { queueApi } from '../services/api'

interface MoveToPositionParams {
  id: number
  position: number
}

export function useMoveToPosition() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ id, position }: MoveToPositionParams) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToPosition(id, position)
    } catch (error: unknown) {
      setIsError(true)
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to move thread to position:', err.response?.data?.detail || err.message)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useMoveToFront() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (id: number) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToFront(id)
    } catch (error: unknown) {
      setIsError(true)
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to move thread to front:', err.response?.data?.detail || err.message)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useMoveToBack() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (id: number) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToBack(id)
    } catch (error: unknown) {
      setIsError(true)
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to move thread to back:', err.response?.data?.detail || err.message)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
