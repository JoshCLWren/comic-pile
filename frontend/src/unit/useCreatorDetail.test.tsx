import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorDetail } from '../hooks/useCreatorDetail'
import { creatorsApi as realCreatorsApi } from '../services/api'
import type { CreatorDetailResponse } from '../services/api'

const getDetail = vi.fn<typeof realCreatorsApi.getDetail>()
const detailApi: Pick<typeof realCreatorsApi, 'getDetail'> = { getDetail }

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function makePage(overrides: Partial<CreatorDetailResponse> = {}): CreatorDetailResponse {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'Test Creator',
      normalized_roles: ['writer'],
      average_rating: 4.5,
      ratings_count: 2,
      read_unrated_count: 1,
      upcoming_count: 3,
    },
    coverage: {
      rated_issues_total: 2,
      rated_issues_with_creator_metadata: 2,
      ratings_complete: true,
      read_unrated_issues_total: 1,
      read_unrated_issues_with_creator_metadata: 1,
      read_unrated_complete: true,
      unread_issues_total: 3,
      unread_issues_with_creator_metadata: 3,
      upcoming_complete: true,
    },
    role_stats: [{ role: 'writer', issue_count: 6, average_rating: 4.5 }],
    rated_issues: [
      {
        issue_id: 11,
        issue_number: '1',
        thread_id: 1,
        thread_title: 'Series A',
        status: 'read',
        roles: ['writer'],
        effective_rating: 5,
        rating_timestamp: '2026-01-02T00:00:00Z',
        sort_key: '11',
      },
    ],
    read_unrated_issues: [],
    upcoming_issues: [],
    next_cursor: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getDetail.mockResolvedValue(makePage())
})

describe('useCreatorDetail (bounded incremental loader)', () => {
  it('fetches one bounded page and exposes summary plus rows', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreatorDetail('creator:7', 50, detailApi), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(getDetail).toHaveBeenCalledTimes(1)
    expect(getDetail).toHaveBeenCalledWith('creator:7', { limit: 50 })
    expect(result.current.summary?.display_name).toBe('Test Creator')
    expect(result.current.ratedIssues).toHaveLength(1)
    expect(result.current.hasMore).toBe(false)
  })

  it('does not fetch for a missing creator key', async () => {
    const wrapper = createWrapper()
    renderHook(() => useCreatorDetail(null, 50, detailApi), { wrapper })

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(getDetail).not.toHaveBeenCalled()
  })

  it('appends later pages without erasing already rendered rows', async () => {
    const secondPage = makePage({
      rated_issues: [
        {
          issue_id: 12,
          issue_number: '2',
          thread_id: 1,
          thread_title: 'Series A',
          status: 'read',
          roles: ['writer'],
          effective_rating: 4,
          rating_timestamp: '2026-01-01T00:00:00Z',
          sort_key: '12',
        },
      ],
      next_cursor: null,
    })
    getDetail
      .mockResolvedValueOnce(makePage({ next_cursor: '50' }))
      .mockResolvedValueOnce(secondPage)

    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreatorDetail('creator:7', 50, detailApi), { wrapper })

    await waitFor(() => expect(result.current.hasMore).toBe(true))
    expect(result.current.ratedIssues).toHaveLength(1)

    await result.current.loadMore()
    await waitFor(() => expect(result.current.ratedIssues).toHaveLength(2))
    expect(getDetail).toHaveBeenCalledTimes(2)
    expect(getDetail).toHaveBeenNthCalledWith(2, 'creator:7', { limit: 50, offset: 50 })
    expect(result.current.ratedIssues.map((row) => row.issue_id)).toEqual([11, 12])
    expect(result.current.hasMore).toBe(false)
  })

  it('surfaces fetch errors', async () => {
    getDetail.mockRejectedValue(new Error('boom'))
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreatorDetail('creator:7', 50, detailApi), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(Error)
  })

  it('no-ops loadMore when there is no next page', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreatorDetail('creator:7', 50, detailApi), { wrapper })

    await waitFor(() => expect(result.current.hasMore).toBe(false))
    await expect(result.current.loadMore()).resolves.toBeUndefined()
    expect(getDetail).toHaveBeenCalledTimes(1)
  })

  it('exposes a refetch that reloads the detail query', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreatorDetail('creator:7', 50, detailApi), { wrapper })

    await waitFor(() => expect(result.current.summary?.display_name).toBe('Test Creator'))
    result.current.refetch()
    await waitFor(() => expect(getDetail).toHaveBeenCalledTimes(2))
  })
})
