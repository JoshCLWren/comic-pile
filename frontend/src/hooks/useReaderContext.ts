import { useQuery } from '@tanstack/react-query'
import { readerContextApi, type ReaderContextResponse } from '../services/api-reader-context'
import { readingOrdersApi } from '../services/api-reading-orders'
import { dependenciesApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { ReadingOrder } from '../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../types'

interface ReaderContextState {
  context: ReaderContextResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ReaderContextState = {
  context: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useReaderContext(issueId: number | null | undefined, enabled = true): ReaderContextState {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: issueId ? queryKeys.readerContext.detail(issueId) : [],
    queryFn: async () => {
      try {
        return await readerContextApi.get(issueId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load reader context')
      }
    },
    enabled: issueId != null && enabled,
  })

  if (issueId == null || !enabled) return EMPTY_STATE

  return {
    context: data ?? null,
    isLoading: isPending,
    // SAFETY: the queryFn normalizes failures to Error, so the query error value is Error | null.
    error: (error as Error | null) ?? null,
    refetch: () => {
      void refetch()
    },
  }
}

export function useReadingOrdersForThread(threadId: number | null, enabled = true) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: threadId ? queryKeys.readingOrders.forThread(threadId) : [],
    queryFn: () => readingOrdersApi.getForThread(threadId!),
    enabled: !!threadId && enabled,
  })

  return {
    readingOrders: data?.reading_orders ?? ([] as ReadingOrder[]),
    isPending,
    isError,
    error,
  }
}

export function useConnectedThreads(threadId: number | null, enabled = true) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: threadId ? queryKeys.dependencies.connected(threadId) : [],
    queryFn: () => dependenciesApi.getConnectedThreads(threadId!),
    enabled: !!threadId && enabled,
  })

  return {
    connectedThreads: data?.connected_threads ?? ([] as ConnectedThreadInfo[]),
    isPending,
    isError,
    error,
  }
}
