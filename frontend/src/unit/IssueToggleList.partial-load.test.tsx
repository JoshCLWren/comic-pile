import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList'
import type { Issue, IssueListResponse } from '../types'

/**
 * Regression coverage for #3764: the Edit Series dialog used to save a
 * partially loaded issue list, which rewrote the thread's issues and destroyed
 * the issues that were never loaded (and their read states).
 *
 * The dialog now refuses to publish a truncated list. Saving stays blocked and
 * no write is sent until a complete load succeeds, and a create whose
 * follow-up refresh comes back incomplete aborts the save instead of replacing
 * the base list with a truncated one.
 */

const mockedIssuesApi = {
  list: vi.fn<IssueToggleListApi['list']>(),
  create: vi.fn<IssueToggleListApi['create']>(),
  markRead: vi.fn<IssueToggleListApi['markRead']>(),
  markUnread: vi.fn<IssueToggleListApi['markUnread']>(),
  delete: vi.fn<IssueToggleListApi['delete']>(),
  reorder: vi.fn<IssueToggleListApi['reorder']>(),
}

const mockedIssueDependenciesApi = {
  listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>(),
}

function buildIssue(issueNumber: number): Issue {
  return {
    id: issueNumber,
    thread_id: 99,
    issue_number: String(issueNumber),
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  }
}

const FULL_ISSUES: Issue[] = [buildIssue(1), buildIssue(2), buildIssue(3)]

function buildListResponse(
  issues: Issue[],
  totalCount: number,
  nextPageToken: string | null = null,
): IssueListResponse {
  return {
    issues,
    total_count: totalCount,
    page_size: 100,
    next_page_token: nextPageToken,
  }
}

function renderDeferredToggleList() {
  const ref = createRef<IssueToggleListHandle>()
  render(
    <IssueToggleList
      ref={ref}
      threadId={99}
      deferred
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedIssueDependenciesApi}
    />,
  )
  return ref
}

beforeEach(() => {
  vi.resetAllMocks()
  mockedIssuesApi.create.mockResolvedValue(buildListResponse([], 0))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedIssueDependenciesApi.listForThread.mockResolvedValue({
    thread_id: 99,
    issues: [],
  })
})

describe('IssueToggleList partial issue load (#3764)', () => {
  it('blocks every write until a complete retry loads the whole issue list', async () => {
    // The server reports three issues, but the pagination ends after two.
    mockedIssuesApi.list.mockResolvedValueOnce(
      buildListResponse(FULL_ISSUES.slice(0, 2), FULL_ISSUES.length),
    )

    const ref = renderDeferredToggleList()

    // The truncated list is never published.
    expect(await screen.findByText(/could not load all issues/i)).toBeInTheDocument()
    expect(screen.queryByTestId('issue-pill-1')).not.toBeInTheDocument()
    expect(screen.getByTestId('issue-load-retry')).toBeInTheDocument()

    // Saving stays blocked and no write is sent.
    await expect(ref.current?.flush()).rejects.toThrow(/not fully loaded/i)
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(mockedIssuesApi.markRead).not.toHaveBeenCalled()
    expect(mockedIssuesApi.markUnread).not.toHaveBeenCalled()
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()

    // A complete retry restores the list and saving.
    mockedIssuesApi.list.mockResolvedValue(
      buildListResponse(FULL_ISSUES, FULL_ISSUES.length),
    )
    fireEvent.click(screen.getByTestId('issue-load-retry'))

    expect(await screen.findByTestId('issue-pill-3')).toBeInTheDocument()
    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()

    // The reader can queue and save a create again.
    mockedIssuesApi.create.mockResolvedValue(
      buildListResponse([buildIssue(4)], FULL_ISSUES.length + 1),
    )
    mockedIssuesApi.list.mockResolvedValue(
      buildListResponse([...FULL_ISSUES, buildIssue(4)], FULL_ISSUES.length + 1),
    )
    fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '4')
  })

  it('aborts the save when the refresh after a queued create is incomplete', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValueOnce(
      buildListResponse(FULL_ISSUES, FULL_ISSUES.length),
    )

    const ref = renderDeferredToggleList()
    expect(await screen.findByTestId('issue-pill-3')).toBeInTheDocument()

    // The create succeeds, but the follow-up refresh comes back truncated.
    mockedIssuesApi.create.mockResolvedValue(
      buildListResponse([buildIssue(4)], FULL_ISSUES.length + 1),
    )
    mockedIssuesApi.list.mockResolvedValue(
      buildListResponse(FULL_ISSUES.slice(0, 2), FULL_ISSUES.length + 1),
    )

    fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    await act(async () => {
      await expect(ref.current?.flush()).rejects.toThrow(/save aborted/i)
    })

    // The truncated refresh is not published as the base list, so no later
    // mutation can be derived from it.
    expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
    expect(screen.getByTestId('issue-pill-2')).toBeInTheDocument()
    expect(screen.getByTestId('issue-pill-3')).toBeInTheDocument()
    expect(screen.getByText(/save aborted/i)).toBeInTheDocument()
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    errorSpy.mockRestore()
  })
})
