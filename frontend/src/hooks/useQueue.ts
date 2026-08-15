import { useCallback, useEffect, useState } from 'react'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queueApi } from '../services/api'
import { threadsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { MoveToPositionPayload, Thread, ThreadListResponse, ThreadQueryParams } from '../types'

export function useQueueThreads(searchTerm?: string) {
  const [data, setData] = useState<Thread[] | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)

  const fetchData = useCallback(async (pageToken?: string) => {
    setIsPending(true)
    setIsError(false)

    try {
      const baseParams: ThreadQueryParams = {}
      if (searchTerm?.trim()) {
        baseParams.search = searchTerm.trim()
      }
      // Bounded initial load: fetch only the first page (default page_size=50)
      if (!pageToken) {
        baseParams.page_size = 50
      }

      const result: ThreadListResponse = await threadsApi.list(
        Object.keys(baseParams).length > 0 ? baseParams : undefined,
        pageToken
      )

      setData(prev => pageToken ? [...(prev ?? []), ...result.threads] : result.threads)
      setNextPageToken(result.next_page_token)
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [searchTerm])

  useEffect(() => {
    void fetchData().catch(() => undefined)
  }, [searchTerm])

  const refetch = useCallback((pageToken?: string): Promise<void> => {
    return fetchData(pageToken)
  }, [fetchData])

  const loadMore = useCallback(async () => {
    if (nextPageToken && !isPending) {
      await fetchData(nextPageToken)
    }
  }, [nextPageToken, isPending, fetchData])

  return { data, isPending, isError, refetch, nextPageToken, loadMore }
}

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
