import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorSeriesIssues } from '../hooks/useCreatorSeriesIssues'
import { creatorsApi } from '../services/api-creators'
import type { CreatorSeriesIssueListResponse } from '../services/api-creators'

const getSeriesIssues = vi.fn<typeof creatorsApi.getSeriesIssues>()
const seriesIssuesApi = { getSeriesIssues }

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const RESPONSE: CreatorSeriesIssueListResponse = {
  series_key: 'thread:7',
  thread_id: 7,
  thread_title: 'Alpha Flight',
  roles: ['cover', 'writer'],
  rated_issue_count: 1,
  average_rating: 3.5,
  lowest_rating: 3.5,
  highest_rating: 3.5,
  metadata_complete: true,
  population_scope: 'all_verified_credits',
  issues: [
    {
      issue_id: 70,
      issue_number: '2',
      thread_id: 7,
      thread_title: 'Alpha Flight',
      status: 'read',
      roles: ['cover'],
      effective_rating: 3.5,
      rating_timestamp: null,
      sort_key: '70',
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
  next_cursor: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  getSeriesIssues.mockResolvedValue(RESPONSE)
})

describe('useCreatorSeriesIssues', () => {
  it('fetches the exact series drill-down when enabled', async () => {
    const { result } = renderHook(
      () => useCreatorSeriesIssues('creator:7', 'thread:7', { seriesIssuesApi }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(getSeriesIssues).toHaveBeenCalledWith('creator:7', 'thread:7')
    expect(result.current.data?.total).toBe(1)
    expect(result.current.data?.population_scope).toBe('all_verified_credits')
  })

  it('does not fetch until the caller enables the drill-down', async () => {
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useCreatorSeriesIssues('creator:7', 'thread:7', { enabled, seriesIssuesApi }),
      { wrapper: createWrapper(), initialProps: { enabled: false } },
    )

    expect(result.current.fetchStatus).toBe('idle')
    expect(getSeriesIssues).not.toHaveBeenCalled()

    rerender({ enabled: true })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(getSeriesIssues).toHaveBeenCalledTimes(1)
  })
})
