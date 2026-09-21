import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RELEASES_PAGE_SIZE, releasesQueryOptions, useReleases } from '../hooks/useReleases'
import { releasesApi, type Release } from '../services/api-releases'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-releases', () => ({
  releasesApi: {
    list: vi.fn(),
  },
}))

const mockedList = vi.mocked(releasesApi.list)

function release(overrides: Partial<Release> = {}): Release {
  return {
    id: 1,
    released_at: '2026-08-11T20:00:00Z',
    category: 'Queue',
    title: 'Queue cards open details',
    summary: 'Selecting a Queue card now opens its thread details reliably.',
    body: null,
    sort_order: 0,
    created_at: '2026-08-11T20:00:00Z',
    updated_at: '2026-08-11T20:00:00Z',
    ...overrides,
  } as Release
}

function pageOf(items: Release[], total: number, offset = 0) {
  return {
    releases: items,
    total,
    limit: RELEASES_PAGE_SIZE,
    offset,
  }
}

function renderWithClient<T>(hook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const rendered = renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
  return { result: rendered.result, client }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('releasesQueryOptions', () => {
  it('builds the canonical releases list key with the offset in pageParam', () => {
    const options = releasesQueryOptions()

    expect(options.queryKey).toEqual(queryKeys.releases.list({ pageSize: RELEASES_PAGE_SIZE }))
    expect(options.initialPageParam).toBe(0)
  })

  it('derives the next offset from the loaded count while items remain', () => {
    const options = releasesQueryOptions()

    expect(
      options.getNextPageParam(pageOf([release({ id: 1 })], 2, 0), [
        pageOf([release({ id: 1 })], 2, 0),
      ]),
    ).toBe(1)
  })

  it('stops paging once the loaded count reaches the total', () => {
    const options = releasesQueryOptions()

    expect(
      options.getNextPageParam(pageOf([release({ id: 1 })], 1, 0), [
        pageOf([release({ id: 1 })], 1, 0),
      ]),
    ).toBeUndefined()
  })
})

describe('useReleases', () => {
  it('loads the first bounded page and reports no more pages when total is reached', async () => {
    mockedList.mockResolvedValue(pageOf([release({ id: 1 })], 1, 0))

    const { result } = renderWithClient(() => useReleases())

    await waitFor(() => expect(result.current.releases).toHaveLength(1))
    expect(mockedList).toHaveBeenCalledWith(RELEASES_PAGE_SIZE, 0)
    expect(result.current.total).toBe(1)
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.hasMore).toBe(false)
  })

  it('appends older releases through loadMore using the loaded count as offset', async () => {
    mockedList
      .mockResolvedValueOnce(pageOf([release({ id: 2, title: 'Newest release' })], 2, 0))
      .mockResolvedValueOnce(
        pageOf([release({ id: 1, title: 'Older release' })], 2, 1),
      )

    const { result } = renderWithClient(() => useReleases())

    await waitFor(() => expect(result.current.releases).toHaveLength(1))
    expect(result.current.hasMore).toBe(true)

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.releases).toHaveLength(2))
    expect(mockedList).toHaveBeenNthCalledWith(1, RELEASES_PAGE_SIZE, 0)
    expect(mockedList).toHaveBeenNthCalledWith(2, RELEASES_PAGE_SIZE, 1)
    expect(result.current.hasMore).toBe(false)
  })

  it('retries the exact failed offset without restarting loaded history', async () => {
    mockedList
      .mockResolvedValueOnce(pageOf([release({ id: 2, title: 'Newest release' })], 2, 0))
      .mockRejectedValueOnce(new Error('older page unavailable'))
      .mockResolvedValueOnce(
        pageOf([release({ id: 1, title: 'Recovered older release' })], 2, 1),
      )

    const { result } = renderWithClient(() => useReleases())

    await waitFor(() => expect(result.current.releases).toHaveLength(1))
    await act(async () => {
      await result.current.loadMore()
    })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error?.message).toBe('older page unavailable')
    expect(result.current.releases).toHaveLength(1)

    await act(async () => {
      await result.current.retry()
    })

    await waitFor(() => expect(result.current.releases).toHaveLength(2))
    expect(mockedList).toHaveBeenNthCalledWith(2, RELEASES_PAGE_SIZE, 1)
    expect(mockedList).toHaveBeenNthCalledWith(3, RELEASES_PAGE_SIZE, 1)
  })

  it('retries the first page through retry when nothing has loaded', async () => {
    mockedList
      .mockRejectedValueOnce(new Error('release API unavailable'))
      .mockResolvedValueOnce(pageOf([], 0, 0))

    const { result } = renderWithClient(() => useReleases())

    await waitFor(() => expect(result.current.isError).toBe(true))

    await act(async () => {
      await result.current.retry()
    })

    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2))
    expect(mockedList).toHaveBeenNthCalledWith(2, RELEASES_PAGE_SIZE, 0)
  })

  it('normalizes non-Error failures to the safe fallback message', async () => {
    mockedList.mockRejectedValue('offline')

    const { result } = renderWithClient(() => useReleases())

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error?.message).toBe('Release notes could not be loaded.')
  })
})
