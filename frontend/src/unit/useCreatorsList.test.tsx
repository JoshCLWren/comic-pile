import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorsList, CREATOR_LIST_PAGE_SIZE } from '../hooks/useCreatorsList'
import type { CreatorListSelection } from '../hooks/useCreatorsList'
import { creatorsApi } from '../services/api-creators'
import type { CreatorListItem, CreatorListResponse } from '../services/api-creators'

vi.mock('../services/api-creators', () => ({
  creatorsApi: {
    getList: vi.fn(),
  },
}))

const mockedGetList = vi.mocked(creatorsApi.getList)

const COMPLETE_COVERAGE = {
  rated_issues_total: 4,
  rated_issues_with_creator_metadata: 4,
  ratings_complete: true,
  read_unrated_issues_total: 1,
  read_unrated_issues_with_creator_metadata: 1,
  read_unrated_complete: true,
  unread_issues_total: 2,
  unread_issues_with_creator_metadata: 2,
  upcoming_complete: true,
}

function makeItem(overrides: Partial<CreatorListItem> & { canonical_creator_key: string }): CreatorListItem {
  return {
    display_name: 'A Creator',
    normalized_roles: ['writer'],
    average_rating: 4,
    ratings_count: 1,
    ...overrides,
  }
}

function makePage(overrides: Partial<CreatorListResponse> = {}): CreatorListResponse {
  return {
    items: [],
    total: 0,
    limit: CREATOR_LIST_PAGE_SIZE,
    offset: 0,
    coverage: COMPLETE_COVERAGE,
    ...overrides,
  }
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useCreatorsList', () => {
  it('requests one bounded page with the normalized selection', async () => {
    mockedGetList.mockResolvedValue(
      makePage({ items: [makeItem({ canonical_creator_key: 'creator:1' })], total: 1 }),
    )

    const { result } = renderHook(() => useCreatorsList({ search: '  bkv  ' }), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetList).toHaveBeenCalledTimes(1)
    expect(mockedGetList).toHaveBeenCalledWith({
      search: 'bkv',
      sort: 'name',
      limit: CREATOR_LIST_PAGE_SIZE,
      offset: 0,
    })
    expect(result.current.items).toHaveLength(1)
    expect(result.current.total).toBe(1)
    expect(result.current.coverage).toEqual(COMPLETE_COVERAGE)
    expect(result.current.hasMore).toBe(false)
  })

  it('appends the next page without dropping loaded rows', async () => {
    mockedGetList
      .mockResolvedValueOnce(
        makePage({
          items: [
            makeItem({ canonical_creator_key: 'creator:1' }),
            makeItem({ canonical_creator_key: 'creator:2' }),
          ],
          total: 3,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          items: [makeItem({ canonical_creator_key: 'creator:3' })],
          total: 3,
          offset: 2,
        }),
      )

    const { result } = renderHook(() => useCreatorsList({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(result.current.hasMore).toBe(true)

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(3))
    expect(mockedGetList).toHaveBeenLastCalledWith({
      search: undefined,
      sort: 'name',
      limit: CREATOR_LIST_PAGE_SIZE,
      offset: 2,
    })
    expect(result.current.items.map((item) => item.canonical_creator_key)).toEqual([
      'creator:1',
      'creator:2',
      'creator:3',
    ])
    expect(result.current.hasMore).toBe(false)
  })

  it('never repeats a canonical creator across a page boundary', async () => {
    mockedGetList
      .mockResolvedValueOnce(
        makePage({
          items: [
            makeItem({ canonical_creator_key: 'creator:1', display_name: 'Alex' }),
            makeItem({ canonical_creator_key: 'creator:2', display_name: 'Alex' }),
          ],
          total: 3,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          items: [
            makeItem({ canonical_creator_key: 'creator:2', display_name: 'Alex' }),
            makeItem({ canonical_creator_key: 'creator:3', display_name: 'Alex' }),
          ],
          total: 3,
          offset: 2,
        }),
      )

    const { result } = renderHook(() => useCreatorsList({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(3))
    expect(result.current.items.map((item) => item.canonical_creator_key)).toEqual([
      'creator:1',
      'creator:2',
      'creator:3',
    ])
  })

  it('stops paginating on a short page so the trigger cannot loop', async () => {
    mockedGetList.mockResolvedValue(makePage({ items: [], total: 12 }))

    const { result } = renderHook(() => useCreatorsList({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.items).toEqual([])
    expect(result.current.total).toBe(12)
    expect(result.current.hasMore).toBe(false)

    await act(async () => {
      await result.current.loadMore()
    })
    expect(mockedGetList).toHaveBeenCalledTimes(1)
  })

  it('sends the selected server-side ordering', async () => {
    mockedGetList.mockResolvedValue(makePage())

    const { result } = renderHook(() => useCreatorsList({ sort: 'average_rating' }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetList).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'average_rating' }),
    )
  })

  it('exposes a failed load without any rows', async () => {
    mockedGetList.mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCreatorsList({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.items).toEqual([])
    expect(result.current.coverage).toBeNull()
  })

  it('refetches the current selection on demand', async () => {
    mockedGetList.mockResolvedValue(makePage({ total: 1 }))

    const { result } = renderHook(() => useCreatorsList({ sort: 'ratings_count' }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetList).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.refetch()
    })

    await waitFor(() => expect(mockedGetList).toHaveBeenCalledTimes(2))
    expect(mockedGetList).toHaveBeenLastCalledWith({
      search: undefined,
      sort: 'ratings_count',
      limit: CREATOR_LIST_PAGE_SIZE,
      offset: 0,
    })
  })

  it('ignores a load-more request when there is no next page', async () => {
    mockedGetList.mockResolvedValue(makePage({ items: [makeItem({ canonical_creator_key: 'creator:1' })], total: 1 }))

    const { result } = renderHook(() => useCreatorsList({}), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.hasMore).toBe(false)

    await act(async () => {
      await result.current.loadMore()
    })

    expect(mockedGetList).toHaveBeenCalledTimes(1)
  })

  it('sends every bounded filter on the wire', async () => {
    mockedGetList.mockResolvedValue(makePage())

    const { result } = renderHook(
      () =>
        useCreatorsList({
          role: '  writer  ',
          minRatings: 3,
          minRating: 4,
          maxRating: 4.5,
          hasUnreadWork: true,
        }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetList).toHaveBeenCalledWith({
      search: undefined,
      sort: 'name',
      limit: CREATOR_LIST_PAGE_SIZE,
      offset: 0,
      min_ratings: 3,
      role: 'writer',
      min_rating: 4,
      max_rating: 4.5,
      has_unread_work: true,
    })
  })

  it('omits rating filters that fall outside the personal 0-5 scale', async () => {
    mockedGetList.mockResolvedValue(makePage())

    const { result } = renderHook(
      () => useCreatorsList({ minRating: -1, maxRating: 7, hasUnreadWork: false }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetList).toHaveBeenCalledWith(
      expect.objectContaining({ min_rating: undefined, max_rating: undefined }),
    )
    // `false` is a real restriction and must still reach the server.
    expect(mockedGetList).toHaveBeenCalledWith(
      expect.objectContaining({ has_unread_work: false }),
    )
  })

  it('resets pagination and keeps the active filters when a filter changes', async () => {
    mockedGetList.mockImplementation(async (params) => {
      const offset = params?.offset ?? 0
      return makePage({
        items: [makeItem({ canonical_creator_key: `creator:${offset + 1}` })],
        total: 40,
        offset,
      })
    })

    const initialSelection: CreatorListSelection = { sort: 'name' }

    const { result, rerender } = renderHook(
      (selection: CreatorListSelection) => useCreatorsList(selection),
      { wrapper: createWrapper(), initialProps: initialSelection },
    )

    await waitFor(() => expect(result.current.items).toHaveLength(1))
    await act(async () => {
      await result.current.loadMore()
    })
    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(mockedGetList).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }))

    rerender({ sort: 'name', role: 'writer' })

    await waitFor(() =>
      expect(mockedGetList).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, role: 'writer' }),
      ),
    )
    // A new key starts a fresh collection rather than appending filtered pages.
    await waitFor(() => expect(result.current.items).toHaveLength(1))
    expect(result.current.total).toBe(40)
  })
})
