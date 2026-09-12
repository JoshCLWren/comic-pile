import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useQueueThreads,
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../hooks/useQueue'
import type { QueueApi, QueueInvalidateFn } from '../hooks/useQueue'
import { threadsApi as realThreadsApi } from '../services/api'
import { queryClient } from '../query/queryClient'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'

const moveToPosition = vi.fn()
const moveToFront = vi.fn()
const moveToBack = vi.fn()
const shuffle = vi.fn()
const invalidate = vi.fn<QueueInvalidateFn>()
const listThreads = vi.fn<typeof realThreadsApi.list>()

const queueApi: QueueApi = { moveToPosition, moveToFront, moveToBack, shuffle }
const threadsApi: Pick<typeof realThreadsApi, 'list'> = { list: listThreads }

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
  moveToPosition.mockResolvedValue(undefined as never)
  moveToFront.mockResolvedValue(undefined as never)
  moveToBack.mockResolvedValue(undefined as never)
  shuffle.mockResolvedValue(undefined as never)
  invalidate.mockResolvedValue()
  listThreads.mockResolvedValue({ threads: [], next_page_token: null })
})

describe('useQueueThreads (bounded incremental loader)', () => {
  it('fetches exactly one bounded page on mount', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(listThreads).toHaveBeenCalledTimes(1)
    expect(listThreads).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toEqual([])
    expect(result.current.nextPageToken).toBeNull()
  })

  it('passes search and default sort on the initial page', async () => {
    listThreads.mockResolvedValue({
      threads: [{ id: 1, title: 'Bat' } as never],
      next_page_token: null,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('bat', 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(listThreads).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'bat', sort: 'position', page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toHaveLength(1)
  })

  it('maps the alphabetical UI sort to the title API sort', async () => {
    listThreads.mockResolvedValue({ threads: [], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('', 'alphabetical' as QueueSortBy, threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(listThreads).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'title' }),
      undefined,
    )
  })

  it('does not include page_size when fetching a later cursor page', async () => {
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(listThreads).toHaveBeenCalledTimes(2)
    expect(listThreads).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ page_size: expect.anything() }),
      'tok-2',
    )
  })

  it('appends later pages without duplicating rows', async () => {
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.data).toHaveLength(2))
    expect(listThreads).toHaveBeenCalledTimes(2)
    expect(result.current.nextPageToken).toBeNull()
  })

  it('loadMore is a no-op when there is no next page', async () => {
    listThreads.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(listThreads).toHaveBeenCalledTimes(1)
  })

  it('reports no next page token at the end of the list', async () => {
    listThreads.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.nextPageToken).toBeNull()
    expect(result.current.data).toHaveLength(1)
  })

  it('sets the error state when the initial request fails', async () => {
    listThreads.mockRejectedValueOnce(new Error('network'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.isPending).toBe(false)
  })

  it('surfaces an incremental-load error without discarding loaded pages', async () => {
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2' })
      .mockRejectedValueOnce(new Error('next page unavailable'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.nextPageToken).toBe('tok-2')
  })

  it('keeps the previous rows visible while a search-key transition fetches', async () => {
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1, title: 'Saga' } as never], next_page_token: null })
      .mockImplementationOnce(() => new Promise(() => {})) // never resolves: search still in flight

    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search, 'position', threadsApi), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data).toHaveLength(1)

    rerender({ search: 'bat' })

    // While the new first page is still fetching, the previously rendered row
    // must NOT be cleared/blanked (keepPreviousData placeholder behavior).
    expect(result.current.data).toEqual([{ id: 1, title: 'Saga' }])
  })

  it('resets to the first compatible page when search changes', async () => {
    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search, 'position', threadsApi), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(listThreads).toHaveBeenCalledTimes(1)

    listThreads.mockClear()
    rerender({ search: 'bat' })

    await waitFor(() =>
      expect(listThreads).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'bat' }),
        undefined,
      ),
    )
    expect(listThreads).toHaveBeenCalledTimes(1)
  })

  it('keeps previous data visible while search query is fetching (#2343 focus retention)', async () => {
    listThreads.mockResolvedValueOnce({
      threads: [{ id: 1, title: 'Batman' } as never],
      next_page_token: null,
    })

    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search, 'position', threadsApi), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data).toContainEqual(expect.objectContaining({ id: 1, title: 'Batman' }))

    listThreads.mockClear()
    listThreads.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () => resolve({ threads: [{ id: 2, title: 'Batgirl' } as never], next_page_token: null }),
            100,
          )
        }),
    )

    rerender({ search: 'bat' })

    // With keepPreviousData, placeholder data keeps the query in a "has data"
    // state, so isPending stays false. The critical fix is that data is NOT
    // null during the fetch, which prevents the full-screen loader from
    // unmounting the search input and dropping focus.
    await waitFor(() => {
      expect(listThreads).toHaveBeenCalled()
      expect(result.current.data).not.toBeNull()
      expect(result.current.data).toContainEqual(expect.objectContaining({ id: 1, title: 'Batman' }))
    })

    await waitFor(() => expect(result.current.data).toContainEqual(expect.objectContaining({ id: 2, title: 'Batgirl' })))
  })

  it('resets and re-requests the first page when sort changes', async () => {
    const wrapper = createWrapper()
    const { result, rerender } = renderHook(
      ({ sort }: { sort: QueueSortBy }) => useQueueThreads('', sort, threadsApi),
      { wrapper, initialProps: { sort: 'position' as QueueSortBy } },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    listThreads.mockClear()

    rerender({ sort: 'created' as QueueSortBy })

    await waitFor(() =>
      expect(listThreads).toHaveBeenCalledWith(
        expect.objectContaining({ sort: 'created' }),
        undefined,
      ),
    )
    expect(listThreads).toHaveBeenCalledTimes(1)
  })
})

it('moves queue position and reconciles only queue-owned read models', async () => {
  const wrapper = createWrapper()
  const { result } = renderHook(() => useMoveToPosition({ api: queueApi, invalidate }), { wrapper })

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(moveToPosition).toHaveBeenCalledWith(4, 2)
  expect(invalidate).toHaveBeenCalledWith(queryClient)
})

it('moves thread to front and back and reconciles after each mutation', async () => {
  const wrapper = createWrapper()
  const { result: frontResult } = renderHook(() => useMoveToFront({ api: queueApi, invalidate }), { wrapper })
  await act(async () => {
    await frontResult.current.mutate(8)
  })

  const { result: backResult } = renderHook(() => useMoveToBack({ api: queueApi, invalidate }), { wrapper })
  await act(async () => {
    await backResult.current.mutate(9)
  })

  expect(moveToFront).toHaveBeenCalledWith(8)
  expect(moveToBack).toHaveBeenCalledWith(9)
  expect(invalidate).toHaveBeenCalledTimes(2)
  expect(invalidate).toHaveBeenNthCalledWith(1, queryClient)
  expect(invalidate).toHaveBeenNthCalledWith(2, queryClient)
})

it('shuffles the queue and reconciles queue-owned read models', async () => {
  const wrapper = createWrapper()
  const { result } = renderHook(() => useShuffleQueue({ api: queueApi, invalidate }), { wrapper })

  await act(async () => {
    await result.current.mutate()
  })

  expect(shuffle).toHaveBeenCalled()
  expect(invalidate).toHaveBeenCalledWith(queryClient)
})

it('does not invalidate cache when a queue mutation fails', async () => {
  moveToFront.mockRejectedValueOnce(new Error('move failed'))
  const wrapper = createWrapper()
  const { result } = renderHook(() => useMoveToFront({ api: queueApi, invalidate }), { wrapper })

  await expect(
    act(async () => {
      await result.current.mutate(8)
    }),
  ).rejects.toThrow('move failed')

  expect(invalidate).not.toHaveBeenCalled()
})
