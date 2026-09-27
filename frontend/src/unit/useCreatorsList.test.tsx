import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorsList, CREATOR_LIST_PAGE_SIZE } from '../hooks/useCreatorsList'
import { creatorsApi } from '../services/api'
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
})
