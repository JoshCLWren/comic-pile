import { useQuery } from '@tanstack/react-query'
import { readingOrdersApi } from '../services/api-reading-orders'
import { dependenciesApi } from '../services/api'
import { queryKeys } from './queryKeys'
import type { ReadingOrder } from '../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../types'

export function useReadingOrdersForThread(threadId: number | null) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: threadId ? queryKeys.readingOrders.forThread(threadId) : [],
    queryFn: () => readingOrdersApi.getForThread(threadId!),
    enabled: !!threadId,
    // SAFETY: null is the intentional initialData while the query is loading or disabled.
    initialData: null as { reading_orders: ReadingOrder[] } | null,
  })

  return {
    readingOrders: data?.reading_orders ?? [],
    isPending,
    isError,
    error,
  }
}

export function useConnectedThreads(threadId: number | null) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: threadId ? queryKeys.dependencies.connected(threadId) : [],
    queryFn: () => dependenciesApi.getConnectedThreads(threadId!),
    enabled: !!threadId,
    // SAFETY: null is the intentional initialData while the query is loading or disabled.
    initialData: null as { connected_threads: ConnectedThreadInfo[] } | null,
  })

  return {
    connectedThreads: data?.connected_threads ?? [],
    isPending,
    isError,
    error,
  }
}