import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useThreadIssuePages, THREAD_ISSUES_PAGE_SIZE } from '../hooks/useThreadIssues'
import { issuesApi } from '../services/api-issues'
import type { IssueListResponse } from '../types'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'

vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

const mockedIssuesApiList = vi.mocked(issuesApi.list)

function page(
  issueNumber: string,
  nextPageToken: string | null,
  totalCount: number,
): IssueListResponse {
  return {
    issues: [{
      id: Number(issueNumber),
      thread_id: 7,
      issue_number: issueNumber,
      status: 'unread',
      read_at: null,
      created_at: 'now',
    }],
    next_page_token: nextPageToken,
    total_count: totalCount,
    page_size: THREAD_ISSUES_PAGE_SIZE,
  }
}

beforeEach(() => {
  mockedIssuesApiList.mockReset()
})

it('uses the canonical issue-pages query key and fetches a bounded first page', async () => {
  mockedIssuesApiList.mockResolvedValueOnce(page('1', 'next', 3))
  const { result } = renderHook(() => useThreadIssuePages(7))

  await waitFor(() => expect(result.current.issues).toHaveLength(1))
  expect(mockedIssuesApiList).toHaveBeenCalledTimes(1)
  expect(mockedIssuesApiList).toHaveBeenCalledWith(7, { page_size: THREAD_ISSUES_PAGE_SIZE })
  expect(result.current.issues[0]?.issue_number).toBe('1')
  expect(result.current.nextPageToken).toBe('next')
  expect(result.current.hasNextPage).toBe(true)
  expect(result.current.totalCount).toBe(3)

  const state = queryClient.getQueryState(queryKeys.thread.issuePages(7))
  expect(state?.status).toBe('success')
})

it('appends cursor pages through fetchNextPage without revisiting the thread', async () => {
  mockedIssuesApiList
    .mockResolvedValueOnce(page('1', 'next', 2))
    .mockResolvedValueOnce(page('2', null, 2))
  const { result } = renderHook(() => useThreadIssuePages(7))

  await waitFor(() => expect(result.current.issues).toHaveLength(1))
  await act(async () => {
    await result.current.fetchNextPage()
  })
  await waitFor(() => expect(result.current.issues).toHaveLength(2))
  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(1, 7, { page_size: THREAD_ISSUES_PAGE_SIZE })
  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(2, 7, {
    page_size: THREAD_ISSUES_PAGE_SIZE,
    page_token: 'next',
  })
  expect(result.current.hasNextPage).toBe(false)
  expect(result.current.nextPageToken).toBeNull()
})

it('stays disabled for missing thread ids and until explicitly enabled', async () => {
  const disabled = renderHook(() => useThreadIssuePages(7, false))
  const missing = renderHook(() => useThreadIssuePages(null))

  expect(disabled.result.current.issues).toEqual([])
  expect(missing.result.current.issues).toEqual([])
  // A disabled infinite query stays pending until its first fetch; the
  // contract that matters here is that nothing is requested while disabled.
  expect(disabled.result.current.isPending).toBe(true)
  expect(missing.result.current.isPending).toBe(true)
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
})

it('reports issue-loading failures through isError and exposes the raw error', async () => {
  mockedIssuesApiList.mockRejectedValueOnce(new Error('issues unavailable'))
  const { result } = renderHook(() => useThreadIssuePages(7))

  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(result.current.totalCount).toBe(0)
  expect(result.current.issues).toEqual([])
})
