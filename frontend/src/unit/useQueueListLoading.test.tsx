import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { QUEUE_PAGE_SIZE } from '../hooks/useQueue'
import { useQueueListLoading } from '../pages/QueuePage/useQueueListLoading'
import { queryKeys } from '../query/queryKeys'
import type { ThreadListResponse } from '../types'

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function queueListKey(search?: string) {
  return queryKeys.queue.list({ search, sort: 'position', pageSize: QUEUE_PAGE_SIZE })
}

describe('useQueueListLoading', () => {
  it('reports loading while a Queue page query is fetching', async () => {
    const client = new QueryClient()
    let resolveFetch: (page: ThreadListResponse) => void = () => undefined
    const pending = new Promise<ThreadListResponse>((resolve) => {
      resolveFetch = resolve
    })
    void client
      .fetchQuery({ queryKey: queueListKey('Saga'), queryFn: () => pending })
      .catch(() => undefined)

    const { result } = renderHook(() => useQueueListLoading(), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() => expect(result.current).toBe(true))

    resolveFetch({ threads: [], active_count: 0 })
    await waitFor(() => expect(result.current).toBe(false))
    client.clear()
  })

  it('reports loading for a search transition keyed to a different term', async () => {
    const client = new QueryClient()
    void client
      .fetchQuery({
        queryKey: queueListKey('Spawn'),
        queryFn: () => new Promise<ThreadListResponse>(() => undefined),
      })
      .catch(() => undefined)

    const { result } = renderHook(() => useQueueListLoading(), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() => expect(result.current).toBe(true))
    client.clear()
  })

  it('ignores fetches that are not Queue pages', async () => {
    const client = new QueryClient()
    void client
      .fetchQuery({
        queryKey: queryKeys.queue.activeCount(),
        queryFn: () => new Promise<number>(() => undefined),
      })
      .catch(() => undefined)

    const { result } = renderHook(() => useQueueListLoading(), {
      wrapper: makeWrapper(client),
    })

    await waitFor(() =>
      expect(client.isFetching({ queryKey: queryKeys.queue.activeCount() })).toBe(1),
    )
    expect(result.current).toBe(false)
    client.clear()
  })

  it('reports not loading when nothing is in flight', () => {
    const client = new QueryClient()
    client.setQueryData(queueListKey('Saga'), { threads: [], active_count: 0 })

    const { result } = renderHook(() => useQueueListLoading(), {
      wrapper: makeWrapper(client),
    })

    expect(result.current).toBe(false)
    client.clear()
  })
})
