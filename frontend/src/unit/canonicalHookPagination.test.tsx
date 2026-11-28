import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useAllThreads, useCrossoverIssuesForRange } from '../hooks/useCrossovers'
import { useThreadIssuesForDependency } from '../hooks/useDependencies'
import { COLLECT_ALL_DEFAULT_MAX_PAGES } from '../pagination/collectAllPages'
import type { Issue, IssueListResponse } from '../types'

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

  it('fails a capped unread issue collection instead of exposing incomplete data', async () => {
    let count = 0
    const list = vi.fn(async () => issuePage([firstIssue], String(++count)))
    const { result } = renderHook(
      () => useThreadIssuesForDependency(7, true, { list }),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(list).toHaveBeenCalledTimes(COLLECT_ALL_DEFAULT_MAX_PAGES)
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
    expect(list).toHaveBeenCalledTimes(COLLECT_ALL_DEFAULT_MAX_PAGES)
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
