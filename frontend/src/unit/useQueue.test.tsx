import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useActiveSeriesCount,
  useQueueThreads,
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../hooks/useQueue'
import type { QueueApi, QueueInvalidateFn } from '../hooks/useQueue'
import { threadsApi as realThreadsApi } from '../services/api-threads'
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
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  // SAFETY: the endpoint returns no body, so the mock resolves to undefined
  moveToPosition.mockResolvedValue(undefined as never)
  // SAFETY: the endpoint returns no body, so the mock resolves to undefined
  moveToFront.mockResolvedValue(undefined as never)
  // SAFETY: the endpoint returns no body, so the mock resolves to undefined
  moveToBack.mockResolvedValue(undefined as never)
  // SAFETY: the endpoint returns no body, so the mock resolves to undefined
  shuffle.mockResolvedValue(undefined as never)
  invalidate.mockResolvedValue()
  listThreads.mockResolvedValue({ threads: [], next_page_token: null, active_count: 0 })
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
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [{ id: 1, title: 'Bat' } as never],
      next_page_token: null,
      active_count: 0,
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
    listThreads.mockResolvedValue({ threads: [], next_page_token: null, active_count: 0 })

    const wrapper = createWrapper()
    // SAFETY: the sort literal is one of the values the sort type allows
    const { result } = renderHook(() => useQueueThreads('', 'alphabetical' as QueueSortBy, threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(listThreads).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'title' }),
      undefined,
    )
  })

  it('does not include page_size when fetching a later cursor page', async () => {
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2', active_count: 0 })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null, active_count: 0 })

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
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2', active_count: 0 })
      .mockResolvedValueOnce({ threads: [{ id: 2 } as never], next_page_token: null, active_count: 0 })

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
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null, active_count: 0 })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(listThreads).toHaveBeenCalledTimes(1)
  })

  it('reports no next page token at the end of the list', async () => {
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads.mockResolvedValue({ threads: [{ id: 1 } as never], next_page_token: null, active_count: 0 })

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
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1 } as never], next_page_token: 'tok-2', active_count: 0 })
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
    // SAFETY: the stubbed page supplies only the fields the pager reads
    listThreads
      .mockResolvedValueOnce({ threads: [{ id: 1, title: 'Saga' } as never], next_page_token: null, active_count: 0 })
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
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [{ id: 1, title: 'Batman' } as never],
      next_page_token: null,
      active_count: 0,
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
              // SAFETY: the stubbed page supplies only the fields the pager reads
              () => resolve({ threads: [{ id: 2, title: 'Batgirl' } as never], next_page_token: null, active_count: 0 }),
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
      // SAFETY: the sort literal is one of the values the sort type allows
      { wrapper, initialProps: { sort: 'position' as QueueSortBy } },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    listThreads.mockClear()

    // SAFETY: the sort literal is one of the values the sort type allows
    rerender({ sort: 'created' as QueueSortBy })

    await waitFor(() =>
      expect(listThreads).toHaveBeenCalledWith(
        expect.objectContaining({ sort: 'created' }),
        undefined,
      ),
    )
    expect(listThreads).toHaveBeenCalledTimes(1)
  })

  it('exposes the first-page filtered_count for the applied search (#3614)', async () => {
    listThreads.mockResolvedValue({
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [{ id: 1, title: 'Alpha One' } as never],
      next_page_token: null,
      active_count: 7,
      filtered_count: 2,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('alpha', 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.filteredCount).toBe(2)
    expect(result.current.activeCount).toBe(7)
    expect(result.current.isPlaceholderData).toBe(false)
  })

  it('marks a search-key transition as placeholder so counts stay unset (#3614)', async () => {
    listThreads
      .mockResolvedValueOnce({
        // SAFETY: the stubbed page supplies only the fields the pager reads
        threads: [{ id: 1, title: 'Saga' } as never],
        next_page_token: null,
        active_count: 5,
        filtered_count: 5,
      })
      .mockImplementationOnce(() => new Promise(() => {})) // never resolves: search still in flight

    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search, 'position', threadsApi), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.filteredCount).toBe(5)

    rerender({ search: 'bat' })

    // The old key's rows and counts stay visible as placeholder data, so a
    // count surface must treat this window as unsettled, not as the new
    // query's answer.
    expect(result.current.isPlaceholderData).toBe(true)
    expect(result.current.data).toEqual([{ id: 1, title: 'Saga' }])
    expect(result.current.resultCountText).toBe('Updating series count…')
  })

  it('keeps the newest search count when an older request settles late (#3614)', async () => {
    let resolveAlpha: (page: Awaited<ReturnType<typeof realThreadsApi.list>>) => void = () => undefined
    listThreads
      .mockResolvedValueOnce({
        threads: [],
        next_page_token: null,
        active_count: 5,
        filtered_count: 5,
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveAlpha = resolve
          }),
      )
      .mockResolvedValueOnce({
        threads: [{ id: 2, title: 'Beta' } as never],
        next_page_token: null,
        active_count: 5,
        filtered_count: 1,
      })

    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ search }: { search: string }) => useQueueThreads(search, 'position', threadsApi), {
      wrapper,
      initialProps: { search: '' },
    })

    await waitFor(() => expect(result.current.resultCountText).toBe('5 of 5 series'))
    rerender({ search: 'alpha' })
    await waitFor(() => expect(result.current.resultCountText).toBe('Updating series count…'))

    rerender({ search: 'beta' })
    await waitFor(() => expect(result.current.resultCountText).toBe('1 of 5 series'))

    resolveAlpha({
      threads: [{ id: 1, title: 'Alpha One' }, { id: 3, title: 'Alpha Two' }],
      next_page_token: null,
      active_count: 5,
      filtered_count: 2,
    })
    await act(async () => {})

    expect(result.current.resultCountText).toBe('1 of 5 series')
  })
})

describe('useQueueThreads result count text (#3614)', () => {
  it('shows M of M for the unfiltered queue', async () => {
    listThreads.mockResolvedValue({
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [],
      next_page_token: null,
      active_count: 5,
      filtered_count: 5,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.resultCountText).toBe('5 of 5 series')
  })

  it('shows N of M for a filtered search', async () => {
    listThreads.mockResolvedValue({
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [{ id: 1, title: 'Alpha One' } as never],
      next_page_token: null,
      active_count: 5,
      filtered_count: 2,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('alpha', 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.resultCountText).toBe('2 of 5 series')
  })

  it('shows 0 of M when nothing matches', async () => {
    listThreads.mockResolvedValue({
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [],
      next_page_token: null,
      active_count: 5,
      filtered_count: 0,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads('zzz', 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.resultCountText).toBe('0 of 5 series')
  })

  it('restates whole-queue totals on a cursor page, not the visible page size', async () => {
    listThreads
      .mockResolvedValueOnce({
        // SAFETY: the stubbed page supplies only the fields the pager reads
        threads: [{ id: 1 } as never],
        next_page_token: 'tok-2',
        active_count: 5,
        filtered_count: 5,
      })
      .mockResolvedValueOnce({
        // SAFETY: the stubbed page supplies only the fields the pager reads
        threads: [{ id: 2 } as never],
        next_page_token: null,
        active_count: 5,
        filtered_count: 5,
      })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    await act(async () => {
      await result.current.loadMore()
    })

    // Two rows are visible but the count must restate the whole-queue totals.
    await waitFor(() => expect(result.current.data).toHaveLength(2))
    expect(result.current.resultCountText).toBe('5 of 5 series')
  })

  it('does not invent a count when the settled response omits filtered_count', async () => {
    listThreads.mockResolvedValue({
      // SAFETY: the stubbed page supplies only the fields the pager reads
      threads: [],
      next_page_token: null,
      active_count: 5,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.resultCountText).toBe('Updating series count…')
  })

  it('shows an unavailable count when the first page fails', async () => {
    listThreads.mockRejectedValue(new Error('Network error'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.resultCountText).toBe('Series count unavailable.')
  })

  it('keeps the settled counts when only a next-page fetch fails', async () => {
    listThreads
      .mockResolvedValueOnce({
        // SAFETY: the stubbed page supplies only the fields the pager reads
        threads: [{ id: 1 } as never],
        next_page_token: 'tok-2',
        active_count: 5,
        filtered_count: 5,
      })
      .mockRejectedValueOnce(new Error('page_token error'))

    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(undefined, 'position', threadsApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.resultCountText).toBe('5 of 5 series')
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

describe('useActiveSeriesCount (bounded whole-queue total)', () => {
  it('issues no request until the confirmation needs the total (#3261)', async () => {
    const wrapper = createWrapper()
    const { result, rerender } = renderHook(({ enabled }: { enabled: boolean }) => useActiveSeriesCount(enabled, threadsApi), {
      wrapper,
      initialProps: { enabled: false },
    })

    expect(result.current).toBeNull()
    expect(listThreads).not.toHaveBeenCalled()

    rerender({ enabled: true })

    await waitFor(() => expect(result.current).toBe(0))
    // One bounded row request, never a hydrated queue page.
    expect(listThreads).toHaveBeenCalledTimes(1)
    expect(listThreads).toHaveBeenCalledWith({ page_size: 1 })
  })

  it('reports null when the bounded total cannot be read', async () => {
    listThreads.mockRejectedValueOnce(new Error('count unavailable'))
    const wrapper = createWrapper()
    const { result } = renderHook(() => useActiveSeriesCount(true, threadsApi), { wrapper })

    await waitFor(() => expect(result.current).toBeNull())
    expect(listThreads).toHaveBeenCalledTimes(1)
  })
})
