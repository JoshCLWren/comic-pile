import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useAllThreads, useCrossoverIssuesForRange } from '../hooks/useCrossovers'
import { useThreadIssuesForDependency } from '../hooks/useDependencies'
import { COLLECT_ALL_DEFAULT_MAX_PAGES } from '../pagination/collectAllPages'
import type { Issue, IssueListResponse, ThreadListItem } from '../types'

const SUPPORTED_ISSUE_PAGES = 100

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const firstIssue: Issue = {
  id: 1, thread_id: 7, issue_number: '1', position: 1, status: 'unread',
  read_at: null, created_at: '2026-01-01T00:00:00Z',
}
const secondIssue: Issue = { ...firstIssue, id: 2, issue_number: '2', position: 2 }
const thread: ThreadListItem = {
  id: 1,
  title: 'Series',
  format: 'single issues',
  issues_remaining: 0,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  created_at: '2026-01-01T00:00:00Z',
}

function issuePage(issues: Issue[], next_page_token: string | null): IssueListResponse {
  return { issues, total_count: 2, page_size: 100, next_page_token }
}

describe('canonical hook pagination', () => {
  it('drains unread dependency issues using the same filter and opaque cursor on every page', async () => {
    const list = vi.fn()
      .mockResolvedValueOnce(issuePage([firstIssue], 'opaque-next'))
      .mockResolvedValueOnce(issuePage([secondIssue], null))
    const { result } = renderHook(
      () => useThreadIssuesForDependency(7, true, { list }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.data).toEqual([firstIssue, secondIssue]))
    expect(list).toHaveBeenCalledTimes(2)
    expect(list).toHaveBeenNthCalledWith(1, 7, { status: 'unread', page_size: 100 })
    expect(list).toHaveBeenNthCalledWith(2, 7, { status: 'unread', page_size: 100, page_token: 'opaque-next' })
  })

  it('preserves repeated-token termination without requesting the token twice', async () => {
    const list = vi.fn()
      .mockResolvedValueOnce(issuePage([firstIssue], 'repeat'))
      .mockResolvedValueOnce(issuePage([secondIssue], 'repeat'))
    const { result } = renderHook(
      () => useThreadIssuesForDependency(7, true, { list }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.data).toEqual([firstIssue, secondIssue]))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('loads the full supported unread issue collection across 100 pages', async () => {
    let count = 0
    const list = vi.fn(async () => issuePage(
      [firstIssue],
      ++count < SUPPORTED_ISSUE_PAGES ? String(count) : null,
    ))
    const { result } = renderHook(
      () => useThreadIssuesForDependency(7, true, { list }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.data).toHaveLength(SUPPORTED_ISSUE_PAGES))
    expect(result.current.isError).toBe(false)
    expect(list).toHaveBeenCalledTimes(SUPPORTED_ISSUE_PAGES)
  })

  it('loads the full supported crossover issue range across 100 pages', async () => {
    let count = 0
    const list = vi.fn(async () => issuePage(
      [firstIssue],
      ++count < SUPPORTED_ISSUE_PAGES ? String(count) : null,
    ))
    const { result } = renderHook(
      () => useCrossoverIssuesForRange(7, { issues: { list } }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.data).toHaveLength(SUPPORTED_ISSUE_PAGES))
    expect(result.current.isError).toBe(false)
    expect(list).toHaveBeenCalledTimes(SUPPORTED_ISSUE_PAGES)
  })

  it('fails a capped unread issue collection instead of exposing incomplete data', async () => {
    let count = 0
    const list = vi.fn(async () => issuePage([firstIssue], String(++count)))
    const { result } = renderHook(
      () => useThreadIssuesForDependency(7, true, { list }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(list).toHaveBeenCalledTimes(SUPPORTED_ISSUE_PAGES)
  })

  it('fails a capped crossover issue range instead of exposing incomplete data', async () => {
    let count = 0
    const list = vi.fn(async () => issuePage([firstIssue], String(++count)))
    const { result } = renderHook(
      () => useCrossoverIssuesForRange(7, { issues: { list } }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(list).toHaveBeenCalledTimes(SUPPORTED_ISSUE_PAGES)
  })

  it('sizes the thread collection bound from the authoritative active count', async () => {
    const threadCount = COLLECT_ALL_DEFAULT_MAX_PAGES * 100 + 1
    let count = 0
    const list = vi.fn(async () => {
      count += 1
      const remaining = threadCount - (count - 1) * 100
      return {
        threads: Array.from(
          { length: Math.min(100, remaining) },
          (_, index) => ({ ...thread, id: (count - 1) * 100 + index + 1 }),
        ),
        active_count: threadCount,
        filtered_count: threadCount,
        next_page_token: remaining > 100 ? String(count) : null,
      }
    })
    const { result } = renderHook(
      () => useAllThreads({ threads: { list } }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.data).toHaveLength(threadCount))
    expect(result.current.isError).toBe(false)
    expect(list).toHaveBeenCalledTimes(COLLECT_ALL_DEFAULT_MAX_PAGES + 1)
  })

  it('fails a capped crossover thread selection instead of exposing incomplete data', async () => {
    let count = 0
    const list = vi.fn().mockImplementation(async () => ({
      threads: [], active_count: 0, next_page_token: String(++count),
    }))
    const { result } = renderHook(
      () => useAllThreads({ threads: { list } }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(list).toHaveBeenCalledTimes(COLLECT_ALL_DEFAULT_MAX_PAGES)
    expect(list).toHaveBeenNthCalledWith(1, { page_size: 100 }, null)
    expect(list).toHaveBeenNthCalledWith(2, { page_size: 100 }, '1')
  })
})
