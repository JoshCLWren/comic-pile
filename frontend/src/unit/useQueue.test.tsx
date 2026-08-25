import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueThreads, useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queueApi, threadsApi } from '../services/api'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'

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

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMovement: vi.fn(),
}))

const mockedQueueApi = vi.mocked(queueApi)
const mockedThreadsApi = vi.mocked(threadsApi)
const mockedInvalidateAfterQueueMovement = vi.mocked(invalidateAfterQueueMovement)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedQueueApi.moveToPosition.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToFront.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToBack.mockResolvedValue(undefined as never)
  mockedQueueApi.shuffle.mockResolvedValue(undefined as never)
  mockedInvalidateAfterQueueMovement.mockResolvedValue()
  mockedThreadsApi.list.mockResolvedValue({ threads: [], next_page_token: null })
})

describe('useQueueThreads (bounded incremental loader)', () => {
  it('fetches exactly one bounded page on mount', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toEqual([])
    expect(result.current.nextPageToken).toBeNull()
  })

  it('passes search and default sort on the initial page', async () => {
    mockedThreadsApi.list.mockResolvedValue({
      threads: [{ id: 1, title: 'Bat' } as never],
      next_page_token: null,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('bat'), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'bat', sort: 'position', page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toHaveLength(1)
  })

  it('maps the alphabetical UI sort to the title API sort', async () => {
    mockedThreadsApi.list.mockResolvedValue({ threads: [], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('', 'alphabetical' as QueueSortBy), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'title' }),
      undefined,
    )
  })

  it('does not include page_size when fetching a later cursor page', async () => {
    mockedThreadsApi.list
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(2)
    expect(mockedThreadsApi.list).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ page_size: expect.anything() }),
      'tok-2',
    )
  })

  it('appends later pages without duplicating rows', async () => {
    mockedThreadsApi.list
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.data).toHaveLength(2))
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(2)
    expect(result.current.nextPageToken).toBeNull()
  })

  it('loadMore is a no-op when there is no next page', async () => {
    mockedThreadsApi.list.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
  })

  it('reports no next page token at the end of the list', async () => {
    mockedThreadsApi.list.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.nextPageToken).toBeNull()
    expect(result.current.data).toHaveLength(1)
  })

  it('sets the error state when the initial request fails', async () => {
    mockedThreadsApi.list.mockRejectedValueOnce(new Error('network'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.isPending).toBe(false)
  })

  it('surfaces an incremental-load error without discarding loaded pages', async () => {
    mockedThreadsApi.list
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockRejectedValueOnce(new Error('next page unavailable'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.nextPageToken).toBe('tok-2')
  })

  it('resets to the first compatible page when search changes', async () => {
    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)

    mockedThreadsApi.list.mockClear()
    rerender({ search: 'bat' })

    await waitFor(() =>
      expect(mockedThreadsApi.list).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'bat' }),
        undefined,
      ),
    )
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
  })

  it('resets and re-requests the first page when sort changes', async () => {
    const wrapper = createWrapper()
    const { result, rerender } = renderHook(
      ({ sort }: { sort: QueueSortBy }) => useQueueThreads('', sort),
      { wrapper, initialProps: { sort: 'position' as QueueSortBy } },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    mockedThreadsApi.list.mockClear()

    rerender({ sort: 'created' as QueueSortBy })

    await waitFor(() =>
      expect(mockedThreadsApi.list).toHaveBeenCalledWith(
        expect.objectContaining({ sort: 'created' }),
        undefined,
      ),
    )
    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
  })
})

it('moves queue position and reconciles only queue-owned read models', async () => {
  const wrapper = createWrapper()
  const { result } = renderHook(() => useMoveToPosition(), { wrapper })

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(mockedQueueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledWith(queryClient)
})

it('moves thread to front and back and reconciles after each mutation', async () => {
  const wrapper = createWrapper()
  const { result: frontResult } = renderHook(() => useMoveToFront(), { wrapper })
  await act(async () => {
    await frontResult.current.mutate(8)
  })

  const { result: backResult } = renderHook(() => useMoveToBack(), { wrapper })
  await act(async () => {
    await backResult.current.mutate(9)
  })

  expect(mockedQueueApi.moveToFront).toHaveBeenCalledWith(8)
  expect(mockedQueueApi.moveToBack).toHaveBeenCalledWith(9)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledTimes(2)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenNthCalledWith(1, queryClient)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenNthCalledWith(2, queryClient)
})

it('shuffles the queue and reconciles queue-owned read models', async () => {
  const wrapper = createWrapper()
  const { result } = renderHook(() => useShuffleQueue(), { wrapper })

  await act(async () => {
    await result.current.mutate()
  })

  expect(mockedQueueApi.shuffle).toHaveBeenCalled()
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledWith(queryClient)
})

it('does not invalidate cache when a queue mutation fails', async () => {
  mockedQueueApi.moveToFront.mockRejectedValueOnce(new Error('move failed'))
  const wrapper = createWrapper()
  const { result } = renderHook(() => useMoveToFront(), { wrapper })

  await expect(
    act(async () => {
      await result.current.mutate(8)
    }),
  ).rejects.toThrow('move failed')

  expect(mockedInvalidateAfterQueueMovement).not.toHaveBeenCalled()
})
