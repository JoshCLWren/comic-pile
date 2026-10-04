import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import { creatorComparisonApi } from '../services/creatorComparisonApi'
import type { CreatorComparisonResponse } from '../types/index'

vi.mock('../services/creatorComparisonApi', () => ({
  creatorComparisonApi: {
    getComparison: vi.fn(),
  },
}))

const mockedGetComparison = vi.mocked(creatorComparisonApi.getComparison)

const COMPLETE_COVERAGE = {
  rated_issues_total: 4,
  rated_issues_with_creator_metadata: 4,
  ratings_complete: true,
  read_unrated_issues_total: 0,
  read_unrated_issues_with_creator_metadata: 0,
  read_unrated_complete: true,
  unread_issues_total: 0,
  unread_issues_with_creator_metadata: 0,
  upcoming_complete: true,
}

function makeResponse(): CreatorComparisonResponse {
  return {
    comparisons: {},
    coverage: COMPLETE_COVERAGE,
    insufficient_data_keys: [],
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
  mockedGetComparison.mockResolvedValue(makeResponse())
})

describe('useCreatorComparison', () => {
  it('fetches one bounded request with deduplicated sorted keys', async () => {
    const { result } = renderHook(
      () => useCreatorComparison(['creator:12', ' creator:7 ', 'creator:12']),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetComparison).toHaveBeenCalledTimes(1)
    expect(mockedGetComparison).toHaveBeenCalledWith(['creator:12', 'creator:7'])
    expect(result.current.data?.coverage).toEqual(COMPLETE_COVERAGE)
    expect(result.current.isError).toBe(false)
  })

  it('does not fetch without at least two keys', async () => {
    renderHook(() => useCreatorComparison(null), { wrapper: createWrapper() })
    renderHook(() => useCreatorComparison([]), { wrapper: createWrapper() })
    renderHook(() => useCreatorComparison(['creator:7']), { wrapper: createWrapper() })

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(mockedGetComparison).not.toHaveBeenCalled()
  })

  it('does not fetch beyond the four-creator bound', async () => {
    renderHook(
      () =>
        useCreatorComparison(['creator:1', 'creator:2', 'creator:3', 'creator:4', 'creator:5']),
      { wrapper: createWrapper() },
    )

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(mockedGetComparison).not.toHaveBeenCalled()
  })

  it('exposes a failed comparison without data', async () => {
    mockedGetComparison.mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCreatorComparison(['creator:7', 'creator:12']), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})
