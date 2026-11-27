import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useThreadIssueCreators } from '../hooks/useThreadIssueCreators'
import { issuesApi } from '../services/api-issues'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    listCreators: vi.fn(),
  },
}))

const mockedListCreators = vi.mocked(issuesApi.listCreators)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useThreadIssueCreators v2 credit projection (#5706)', () => {
  it('drains bounded v2 pages into one issue-keyed map', async () => {
    mockedListCreators
      .mockResolvedValueOnce({
        thread_id: 1,
        issues: [{ issue_id: 1, creators: [{ creator_id: 7, name: 'Writer', roles: ['writer'] }] }],
        total_count: 2,
        page_size: 100,
        next_page_token: '1',
      })
      .mockResolvedValueOnce({
        thread_id: 1,
        issues: [{ issue_id: 2, creators: [{ creator_id: 9, name: 'Artist', roles: ['artist'] }] }],
        total_count: 2,
        page_size: 100,
        next_page_token: null,
      })

    const { result } = renderHook(() => useThreadIssueCreators(1), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.isError).toBe(false)
    expect([...result.current.creatorsByIssueId.keys()]).toEqual([1, 2])
    expect(result.current.creatorsByIssueId.get(1)?.[0]?.name).toBe('Writer')
    expect(result.current.creatorsByIssueId.get(2)?.[0]?.name).toBe('Artist')
    expect(mockedListCreators).toHaveBeenNthCalledWith(1, 1, { page_size: 100 })
    expect(mockedListCreators).toHaveBeenNthCalledWith(2, 1, {
      page_size: 100,
      page_token: '1',
    })
  })

  it('stops when a continuation token repeats', async () => {
    mockedListCreators.mockResolvedValue({
      thread_id: 1,
      issues: [],
      total_count: 0,
      page_size: 100,
      next_page_token: 'loop',
    })

    const { result } = renderHook(() => useThreadIssueCreators(1), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedListCreators).toHaveBeenCalledTimes(2)
    expect(result.current.creatorsByIssueId.size).toBe(0)
  })
})
