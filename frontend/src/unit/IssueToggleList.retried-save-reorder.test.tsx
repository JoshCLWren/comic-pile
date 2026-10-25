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
 * Regression coverage for #4113 / Greptile on PR #4030:
 * https://github.com/JoshCLWren/comic-pile/pull/4030#discussion_r4342711590
 *
 * After a create succeeds, an incomplete refresh used to leave
 * fullyLoadedRef true while baseIssuesRef still lacked the new issue. The
 * next Save passed the load guard, sent a stale reorder (missing the new
 * id), and then dropped that failed reorder from the queue.
 *
 * Incomplete refresh must block the stale flush, keep pending reorder
 * intent, and offer Retry. A successful complete reload must allow Save
 * again with a reorder that includes the new issue.
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
const WITH_NEW_ISSUE: Issue[] = [...FULL_ISSUES, buildIssue(4)]

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

describe('IssueToggleList retried Save after incomplete create refresh (#4113)', () => {
  it.each(['incomplete', 'rejected'] as const)('keeps pending reorder after %s refresh and recovers after Retry', async (failure) => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValueOnce(
      buildListResponse(FULL_ISSUES, FULL_ISSUES.length),
    )

    const ref = renderDeferredToggleList()
    expect(await screen.findByTestId('issue-pill-3')).toBeInTheDocument()

    // Queue a create, then a reorder of the existing issues.
    fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    // Create succeeds on the server; post-create refresh and catch resync
    // both come back truncated (missing the new issue in the published base).
    mockedIssuesApi.create.mockResolvedValue(
      buildListResponse([buildIssue(4)], FULL_ISSUES.length + 1),
    )
    if (failure === 'rejected') {
      mockedIssuesApi.list.mockRejectedValue(new Error('refresh unavailable'))
    } else {
      mockedIssuesApi.list.mockResolvedValue(
        buildListResponse(FULL_ISSUES.slice(0, 2), FULL_ISSUES.length + 1),
      )
    }

    await act(async () => {
      await expect(ref.current?.flush()).rejects.toThrow(/save aborted|resync failed/i)
    })

    expect(mockedIssuesApi.create).toHaveBeenCalledTimes(1)
    // No reorder may leave while the base list is untrusted.
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(screen.getByTestId('issue-load-retry')).toBeInTheDocument()
    expect(screen.getByTestId('issue-action-error')).toBeInTheDocument()

    // A retried Save must not send the stale reorder; pending intent stays.
    await act(async () => {
      await expect(ref.current?.flush()).rejects.toThrow(/not fully loaded/i)
    })
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(screen.getByTestId('issue-load-retry')).toBeInTheDocument()

    // Complete reload restores the list (including the new issue) and clears
    // the aborted-save block so Save can flush the retained reorder.
    mockedIssuesApi.list.mockResolvedValue(
      buildListResponse(WITH_NEW_ISSUE, WITH_NEW_ISSUE.length),
    )
    fireEvent.click(screen.getByTestId('issue-load-retry'))

    // Reorder mode was active before the incomplete refresh; after reload the
    // new issue appears in the reorder list (not the collapsed pill strip).
    expect(await screen.findByTestId('issue-reorder-row-4')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-load-retry')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(true)

    await act(async () => {
      await ref.current?.flush()
    })

    expect(mockedIssuesApi.reorder).toHaveBeenCalledTimes(1)
    const reorderIds = mockedIssuesApi.reorder.mock.calls[0]?.[1]
    expect(reorderIds).toEqual(expect.arrayContaining([1, 2, 3, 4]))
    expect(reorderIds).toHaveLength(4)
    // Moved #1 down before the create flush; relative order among the
    // pre-existing ids is preserved, and the new issue is present.
    expect(reorderIds.indexOf(2)).toBeLessThan(reorderIds.indexOf(1))
    expect(ref.current?.hasPendingMutations()).toBe(false)

    errorSpy.mockRestore()
  })

  it('allows Save after automatic catch-path recovery without manual Retry', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValueOnce(
      buildListResponse(FULL_ISSUES, FULL_ISSUES.length),
    )

    const ref = renderDeferredToggleList()
    expect(await screen.findByTestId('issue-pill-3')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    mockedIssuesApi.create.mockResolvedValue(
      buildListResponse([buildIssue(4)], FULL_ISSUES.length + 1),
    )
    // Post-create refresh fails; automatic catch-path resync is complete.
    mockedIssuesApi.list
      .mockRejectedValueOnce(new Error('refresh unavailable'))
      .mockResolvedValue(
        buildListResponse(WITH_NEW_ISSUE, WITH_NEW_ISSUE.length),
      )

    await act(async () => {
      await expect(ref.current?.flush()).rejects.toThrow(/refresh unavailable/i)
    })
    expect(await screen.findByTestId('issue-reorder-row-4')).toBeInTheDocument()
    // Retry must not remain after a complete reload, or Save looks permanently blocked.
    expect(screen.queryByTestId('issue-load-retry')).not.toBeInTheDocument()
    // The failed Save remains reported until the next successful Save.
    expect(screen.getByTestId('issue-action-error')).toHaveTextContent('refresh unavailable')

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledTimes(1)
    expect(mockedIssuesApi.reorder.mock.calls[0]?.[1]).toEqual(
      expect.arrayContaining([4]),
    )

    errorSpy.mockRestore()
  })
})
