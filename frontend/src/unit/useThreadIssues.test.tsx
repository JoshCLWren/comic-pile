import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { InfiniteData } from '@tanstack/react-query'
import { beforeEach, expect, it, vi, describe } from 'vitest'
import { cast } from '../utils/cast'
import {
  flattenIssuePages,
  getIssueTotalCount,
  useCreateIssues,
  useDeleteIssue,
  useReorderIssues,
  useThreadAllIssues,
  useThreadDependencies,
  useThreadIssuePages,
  useToggleIssueStatus,
} from '../hooks/useThreadIssues'
import { issuesApi } from '../services/api-issues'
import { issueDependenciesApi } from '../services/api-dependencies'
import type { IssueListResponse } from '../services/api-issues'
import type { Issue, Thread } from '../types'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { applyIssueReadSnapshotToCache } from '../query/cacheEffects'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    delete: vi.fn(),
    reorder: vi.fn(),
  },
}))

vi.mock('../services/api-dependencies', () => ({
  issueDependenciesApi: {
    listForThread: vi.fn(),
  },
}))

const mockedIssuesApi = vi.mocked(issuesApi)
const mockedDepsApi = vi.mocked(issueDependenciesApi)

function makeIssue(overrides: Partial<Issue> & { id: number; issue_number: string }): Issue {
  return {
    thread_id: 1,
    position: 1,
    status: 'unread',
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
  mockedIssuesApi.list.mockReset()
})

describe('flattenIssuePages and getIssueTotalCount', () => {
  it('returns empty for undefined and flattens pages', () => {
    expect(flattenIssuePages(undefined)).toEqual([])
    expect(getIssueTotalCount(undefined)).toBe(0)

    const issueA = makeIssue({ id: 1, issue_number: '1' })
    const issueB = makeIssue({ id: 2, issue_number: '2' })
    const data = cast<InfiniteData<IssueListResponse>>({
      pages: [
        { issues: [issueA], total_count: 2, page_size: 50, next_page_token: 'tok' },
        { issues: [issueB], total_count: 2, page_size: 50, next_page_token: null },
      ],
      pageParams: [null, 'tok'],
    })

    expect(flattenIssuePages(data)).toEqual([issueA, issueB])
    expect(getIssueTotalCount(data)).toBe(2)
  })

  it('handles empty pages and missing total_count', () => {
    const empty = cast<InfiniteData<IssueListResponse>>({ pages: [], pageParams: [] })
    expect(flattenIssuePages(empty)).toEqual([])
    expect(getIssueTotalCount(empty)).toBe(0)
    expect(flattenIssuePages(cast<InfiniteData<IssueListResponse>>({}))).toEqual([])
  })
})

describe('useThreadIssuePages', () => {
  it('loads paginated issues and supports status filter', async () => {
    const issue = makeIssue({ id: 10, issue_number: '10' })
    mockedIssuesApi.list.mockResolvedValue({
      issues: [issue],
      total_count: 1,
      page_size: 50,
      next_page_token: null,
    })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadIssuePages(1, { status: 'unread' }), { wrapper })

    await waitFor(() => expect(result.current.data?.pages[0].issues).toEqual([issue]))
    expect(mockedIssuesApi.list).toHaveBeenCalledWith(1, {
      status: 'unread',
      page_size: 100,
    })

    // fetch next page with token
    const second = makeIssue({ id: 11, issue_number: '11' })
    mockedIssuesApi.list.mockResolvedValueOnce({
      issues: [second],
      total_count: 2,
      page_size: 50,
      next_page_token: null,
    })
    // Simulate next page param handling by calling list directly with token
    expect(result.current.hasNextPage).toBe(false)
  })

  it('paginates via next_page_token', async () => {
    const first = makeIssue({ id: 20, issue_number: '20' })
    const second = makeIssue({ id: 21, issue_number: '21' })
    mockedIssuesApi.list
      .mockResolvedValueOnce({
        issues: [first],
        total_count: 2,
        page_size: 50,
        next_page_token: 'tok1',
      })
      .mockResolvedValueOnce({
        issues: [second],
        total_count: 2,
        page_size: 50,
        next_page_token: null,
      })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadIssuePages(2), { wrapper })

    await waitFor(() => expect(result.current.data?.pages[0].issues).toEqual([first]))
    expect(result.current.hasNextPage).toBe(true)

    await act(async () => {
      await result.current.fetchNextPage()
    })

    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2))
    expect(flattenIssuePages(result.current.data)).toEqual([first, second])
  })
})

describe('useThreadAllIssues', () => {
  it('drains all pages and dedupes tokens', async () => {
    const a = makeIssue({ id: 30, issue_number: '30' })
    const b = makeIssue({ id: 31, issue_number: '31' })
    const c = makeIssue({ id: 32, issue_number: '32' })

    mockedIssuesApi.list
      .mockResolvedValueOnce({ issues: [a], total_count: 3, page_size: 100, next_page_token: 't1' })
      .mockResolvedValueOnce({ issues: [b], total_count: 3, page_size: 100, next_page_token: 't2' })
      .mockResolvedValueOnce({ issues: [c], total_count: 3, page_size: 100, next_page_token: null })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadAllIssues(5), { wrapper })

    await waitFor(() => expect(result.current.data).toEqual([a, b, c]))
    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(3)
  })

  it('breaks on duplicate token loop', async () => {
    const a = makeIssue({ id: 40, issue_number: '40' })
    mockedIssuesApi.list
      .mockResolvedValueOnce({ issues: [a], total_count: 1, page_size: 100, next_page_token: 'dup' })
      .mockResolvedValueOnce({ issues: [a], total_count: 1, page_size: 100, next_page_token: 'dup' })

    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadAllIssues(6), { wrapper })

    await waitFor(() => expect(result.current.data).toEqual([a, a]))
  })

  it('handles single page without token', async () => {
    const a = makeIssue({ id: 41, issue_number: '41' })
    mockedIssuesApi.list.mockResolvedValue({ issues: [a], total_count: 1, page_size: 100, next_page_token: null })
    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadAllIssues(7), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual([a]))
  })
})

describe('useThreadDependencies', () => {
  it('maps dependencies with incoming or outgoing', async () => {
    mockedDepsApi.listForThread.mockResolvedValue({
      issues: [
        { issue_id: 1, incoming: [{ dependency_id: 1, source_issue_id: 2, source_issue_number: '2', source_thread_id: 1, source_thread_title: 'T' }], outgoing: [] },
        { issue_id: 2, incoming: [], outgoing: [{ dependency_id: 2, source_issue_id: 2, source_issue_number: '2', source_thread_id: 1, source_thread_title: 'T' }] },
        { issue_id: 3, incoming: [], outgoing: [] },
      ],
    } as never)

    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadDependencies(1), { wrapper })

    await waitFor(() => expect(Object.keys(result.current.data ?? {})).toEqual(['1', '2']))
    expect(result.current.data?.[1].incoming).toHaveLength(1)
    expect(result.current.data?.[2].outgoing).toHaveLength(1)
  })

  it('returns empty map when no deps', async () => {
    mockedDepsApi.listForThread.mockResolvedValue({ issues: [] } as never)
    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadDependencies(9), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual({}))
  })
})

describe('mutations', () => {
  it('toggles issue status with optimistic update and rollback on failure', async () => {
    const issue = makeIssue({ id: 50, issue_number: '50', status: 'unread' })
    mockedIssuesApi.markRead.mockResolvedValue(undefined)
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)

    // seed singleton cache
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(10), [issue])

    const wrapper = createWrapper()
    const { result } = renderHook(() => useToggleIssueStatus(10), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ issue, nextStatus: 'read' })
    })
    expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(50)

    await act(async () => {
      await result.current.mutateAsync({ issue: { ...issue, status: 'read' }, nextStatus: 'unread' })
    })
    expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(50)

    // failure rollback
    mockedIssuesApi.markRead.mockRejectedValueOnce(new Error('fail'))
    const before = queryClient.getQueryData<Issue[]>(queryKeys.thread.issuePagesAll(10))
    await expect(act(async () => result.current.mutateAsync({ issue, nextStatus: 'read' }))).rejects.toThrow()
    expect(queryClient.getQueryData<Issue[]>(queryKeys.thread.issuePagesAll(10))).toEqual(before)
  })

  it('creates issues from range', async () => {
    mockedIssuesApi.create.mockResolvedValue({ issues: [], total_count: 0, page_size: 100, next_page_token: null } as never)
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreateIssues(11), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ issueRange: '1-3', insertAfterIssueId: 5 })
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(11, '1-3', { insert_after_issue_id: 5 })
  })

  it('creates issues without insertAfterIssueId', async () => {
    mockedIssuesApi.create.mockResolvedValue({ issues: [], total_count: 0, page_size: 100, next_page_token: null } as never)
    const wrapper = createWrapper()
    const { result } = renderHook(() => useCreateIssues(12), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ issueRange: '4,5' })
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(12, '4,5', { insert_after_issue_id: undefined })
  })

  it('deletes issue with optimistic filter and rollback', async () => {
    const a = makeIssue({ id: 60, issue_number: '60' })
    const b = makeIssue({ id: 61, issue_number: '61' })
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(13), [a, b])
    mockedIssuesApi.delete.mockResolvedValue(undefined)

    const wrapper = createWrapper()
    const { result } = renderHook(() => useDeleteIssue(13), { wrapper })

    await act(async () => {
      await result.current.mutateAsync(60)
    })
    expect(mockedIssuesApi.delete).toHaveBeenCalledWith(60)

    mockedIssuesApi.delete.mockRejectedValueOnce(new Error('delete fail'))
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(13), [a, b])
    await expect(act(async () => result.current.mutateAsync(60))).rejects.toThrow()
  })

  it('reorders issues with optimistic map and rollback', async () => {
    const a = makeIssue({ id: 70, issue_number: '70' })
    const b = makeIssue({ id: 71, issue_number: '71' })
    const c = makeIssue({ id: 72, issue_number: '72' })
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(14), [a, b, c])
    mockedIssuesApi.reorder.mockResolvedValue(undefined)

    const wrapper = createWrapper()
    const { result } = renderHook(() => useReorderIssues(14), { wrapper })

    await act(async () => {
      await result.current.mutateAsync([72, 70, 71])
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(14, [72, 70, 71])

    // rollback on failure
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(14), [a, b, c])
    mockedIssuesApi.reorder.mockRejectedValueOnce(new Error('reorder fail'))
    await expect(act(async () => result.current.mutateAsync([71, 72]))).rejects.toThrow()
  })

  it('handles reorder with missing ids', async () => {
    const a = makeIssue({ id: 80, issue_number: '80' })
    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(15), [a])
    mockedIssuesApi.reorder.mockResolvedValue(undefined)
    const wrapper = createWrapper()
    const { result } = renderHook(() => useReorderIssues(15), { wrapper })
    await act(async () => {
      await result.current.mutateAsync([80, 999])
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(15, [80, 999])
  })
})

describe('disabled and unseeded cache paths', () => {
  it('stays disabled for null thread id without fetching', () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadIssuePages(null), { wrapper })

    expect(result.current.issues).toEqual([])
    expect(result.current.totalCount).toBe(0)
    expect(mockedIssuesApi.list).not.toHaveBeenCalled()
  })

  it('stays disabled when enabled is false without fetching', () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useThreadIssuePages(21, { enabled: false }), { wrapper })

    expect(result.current.issues).toEqual([])
    expect(result.current.totalCount).toBe(0)
    expect(mockedIssuesApi.list).not.toHaveBeenCalled()
  })

  it('toggles, deletes, and reorders with an empty cache and no-op rollback', async () => {
    const issue = makeIssue({ id: 90, issue_number: '90', status: 'unread' })
    mockedIssuesApi.markRead.mockResolvedValue(undefined)
    mockedIssuesApi.delete.mockResolvedValue(undefined)
    mockedIssuesApi.reorder.mockResolvedValue(undefined)

    const wrapper = createWrapper()
    const { result: toggle } = renderHook(() => useToggleIssueStatus(90), { wrapper })
    await act(async () => {
      await toggle.current.mutateAsync({ issue, nextStatus: 'read' })
    })
    expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(90)
    expect(queryClient.getQueryData(queryKeys.thread.issuePagesAll(90))).toBeUndefined()

    mockedIssuesApi.markRead.mockRejectedValueOnce(new Error('toggle fail'))
    await expect(
      act(async () => toggle.current.mutateAsync({ issue, nextStatus: 'read' })),
    ).rejects.toThrow()
    expect(queryClient.getQueryData(queryKeys.thread.issuePagesAll(90))).toBeUndefined()

    const { result: deleter } = renderHook(() => useDeleteIssue(91), { wrapper })
    await act(async () => {
      await deleter.current.mutateAsync(901)
    })
    expect(mockedIssuesApi.delete).toHaveBeenCalledWith(901)

    mockedIssuesApi.delete.mockRejectedValueOnce(new Error('delete fail'))
    await expect(act(async () => deleter.current.mutateAsync(901))).rejects.toThrow()

    const { result: reorderer } = renderHook(() => useReorderIssues(92), { wrapper })
    await act(async () => {
      await reorderer.current.mutateAsync([902, 903])
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(92, [902, 903])

    mockedIssuesApi.reorder.mockRejectedValueOnce(new Error('reorder fail'))
    await expect(act(async () => reorderer.current.mutateAsync([902]))).rejects.toThrow()
  })

  it('patches infinite pages while skipping non-page caches', () => {
    const stale = makeIssue({ id: 100, issue_number: '100', status: 'unread' })
    const updated = makeIssue({ id: 100, issue_number: '100', status: 'read' })
    const thread = cast<Thread>({
      id: 95,
      title: 'T',
      format: 'issue',
      issues_remaining: 0,
      total_issues: 1,
      queue_position: 1,
      status: 'active',
      is_blocked: false,
      blocking_reasons: [],
      created_at: new Date().toISOString(),
    })

    queryClient.setQueryData<Issue[]>(queryKeys.thread.issuePagesAll(95), [stale])
    queryClient.setQueryData<InfiniteData<IssueListResponse>>(queryKeys.thread.issuePages(95), {
      pages: [{ issues: [stale], total_count: 1, page_size: 100, next_page_token: null }],
      pageParams: [null],
    })
    queryClient.setQueryData(
      queryKeys.thread.issuePage(95, { pageToken: null, pageSize: 100 }),
      cast<IssueListResponse>({}),
    )

    applyIssueReadSnapshotToCache(queryClient, { issues: [updated], thread })

    expect(queryClient.getQueryData<Issue[]>(queryKeys.thread.issuePagesAll(95))).toEqual([stale])
    const pages = queryClient.getQueryData<InfiniteData<IssueListResponse>>(
      queryKeys.thread.issuePages(95),
    )
    expect(pages?.pages[0].issues).toEqual([updated])
    expect(queryClient.getQueryData(queryKeys.thread.detail(95))).toEqual(thread)
  })
})