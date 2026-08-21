import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueThreads } from '../hooks/useQueue'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

vi.mock('../services/api', () => ({
  queueApi: {
    moveToPosition: vi.fn(),
    moveToFront: vi.fn(),
    moveToBack: vi.fn(),
    shuffle: vi.fn(),
  },
  threadsApi: {
    list: vi.fn(),
  },
}))

const mockedThreadsApi = vi.mocked(threadsApi)

function thread(id: number): Thread {
  return {
    id,
    title: `Thread ${id}`,
    format: 'Comic',
    issues_remaining: 1,
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    created_at: '2026-01-01T00:00:00Z',
    total_issues: 10,
    last_activity_at: null,
    next_unread_issue_number: null,
  } as Thread
}

describe('queue mutation pagination reset (#933)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('re-requests exactly one bounded first page instead of every loaded page', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    mockedThreadsApi.list
      .mockResolvedValueOnce({
        threads: [thread(1), thread(2)],
        next_page_token: 'cursor-2',
      })
      .mockResolvedValueOnce({
        threads: [thread(3)],
        next_page_token: null,
      })
      .mockResolvedValue({
        threads: [thread(9)],
        next_page_token: 'cursor-2-fresh',
      })

    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    await act(async () => {
      await result.current.loadMore()
    })
    await waitFor(() => expect(result.current.data).toHaveLength(3))
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(2)

    mockedThreadsApi.list.mockClear()
    await act(async () => {
      await invalidateAfterQueueMovement(client)
    })

    // The pre-mutation cursor must never be replayed: the loader restarts
    // from the first compatible page with an explicit bounded page_size.
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }),
      undefined,
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data).toEqual([thread(9)])
  })

  it('drops loaded pages so mutation-followed paging cannot duplicate rows', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    mockedThreadsApi.list
      .mockResolvedValueOnce({
        threads: [thread(1), thread(2)],
        next_page_token: 'cursor-2',
      })
      .mockResolvedValueOnce({
        threads: [thread(3)],
        next_page_token: null,
      })
      .mockResolvedValue({
        threads: [],
        next_page_token: null,
      })

    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    await act(async () => {
      await result.current.loadMore()
    })
    await waitFor(() => expect(result.current.data).toHaveLength(3))

    await act(async () => {
      await invalidateAfterQueueMovement(client)
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    const ids = (result.current.data ?? []).map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).not.toContain(3)
  })

  it('still refreshes session and roll bootstrap read models', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    await act(async () => {
      await invalidateAfterQueueMovement(client)
    })

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['session', 'current'],
      exact: true,
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['roll', 'bootstrap'],
      exact: true,
    })
  })
})
