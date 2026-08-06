import { useCallback, useState } from 'react'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queueApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { MoveToPositionPayload } from '../types'

export function useMoveToPosition() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ id, position }: MoveToPositionPayload) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToPosition(id, position)
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to position:', getApiErrorDetail(error))
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
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to front:', getApiErrorDetail(error))
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
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to back:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useShuffleQueue() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async () => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.shuffle()
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to shuffle queue:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
