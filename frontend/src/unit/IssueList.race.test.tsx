import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueList } from '../components/IssueList'
import { issueDependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import type { Issue, IssueDependenciesResponse, IssueListResponse, Thread } from '../types'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    move: vi.fn(),
    reorder: vi.fn(),
    delete: vi.fn(),
    migrateThread: vi.fn(),
  },
}))

vi.mock('../services/api-dependencies', () => ({
  issueDependenciesApi: {
    listForThread: vi.fn(),
  },
}))

const mockedIssuesApi = vi.mocked(issuesApi, { deep: true })
const mockedIssueDependenciesApi = vi.mocked(issueDependenciesApi, { deep: true })

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })

  return { promise, reject, resolve }
}

const buildIssue = (
  id: number,
  threadId: number,
  issueNumber: string,
  status: 'read' | 'unread' = 'unread',
): Issue => ({
  id,
  thread_id: threadId,
  issue_number: issueNumber,
  status,
  read_at: status === 'read' ? '2026-03-08T00:00:00Z' : null,
  created_at: '2026-03-08T00:00:00Z',
})

const buildListResponse = (
  issues: Issue[],
  nextPageToken: string | null = null,
  totalCount = issues.length,
): IssueListResponse => ({
  issues,
  total_count: totalCount,
  page_size: 50,
  next_page_token: nextPageToken,
})

const emptyDependencies = (issue: Issue): IssueDependenciesResponse => ({
  issue_id: issue.id,
  incoming: [],
  outgoing: [],
})

const buildThread = (id: number): Thread => ({
  id,
  title: `Thread ${id}`,
  format: 'Comic',
  issues_remaining: 10,
  total_issues: null,
  reading_progress: null,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  next_unread_issue_id: null,
  next_unread_issue_number: null,
})

describe('IssueList request races and rollback isolation', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockedIssueDependenciesApi.listForThread.mockImplementation(async (threadId) => ({
      thread_id: threadId,
      issues: [],
    }))
  })

  it('ignores an older issue response after the thread changes', async () => {
    const oldResponse = createDeferred<IssueListResponse>()
    const oldIssue = buildIssue(1, 99, '1')
    const newIssue = buildIssue(100, 100, '100')

    mockedIssuesApi.list
      .mockImplementationOnce(() => oldResponse.promise)
      .mockResolvedValueOnce(buildListResponse([newIssue]))

    const { rerender } = render(<IssueList thread={buildThread(99)} />)
    await waitFor(() => expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1))

    rerender(<IssueList thread={buildThread(100)} />)
    await waitFor(() => expect(screen.getByText('#100')).toBeInTheDocument())

    await act(async () => {
      oldResponse.resolve(buildListResponse([oldIssue]))
      await oldResponse.promise
    })

    expect(screen.getByText('#100')).toBeInTheDocument()
    expect(screen.queryByText('#1')).not.toBeInTheDocument()
  })

  it('ignores an older dependency response after the thread changes', async () => {
    const oldDependencies = createDeferred<{
      thread_id: number
      issues: IssueDependenciesResponse[]
    }>()
    const issue = buildIssue(1, 99, '1')

    mockedIssuesApi.list.mockResolvedValue(buildListResponse([issue]))
    mockedIssueDependenciesApi.listForThread
      .mockImplementationOnce(() => oldDependencies.promise)
      .mockResolvedValueOnce({
        thread_id: 100,
        issues: [emptyDependencies(issue)],
      })

    const { rerender } = render(<IssueList thread={buildThread(99)} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    rerender(<IssueList thread={buildThread(100)} />)
    await waitFor(() => expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(2))

    await act(async () => {
      oldDependencies.resolve({
        thread_id: 99,
        issues: [
          {
            issue_id: issue.id,
            incoming: [
              {
                dependency_id: 2,
                source_issue_id: 2,
                source_issue_number: '2',
                source_thread_id: 20,
                source_thread_title: 'Source',
              },
            ],
            outgoing: [],
          },
        ],
      })
      await oldDependencies.promise
    })

    expect(screen.queryByTitle('Has dependencies')).not.toBeInTheDocument()
  })

  it('rolls back only the failed issue and preserves another successful toggle', async () => {
    const firstToggle = createDeferred<void>()
    const firstIssue = buildIssue(1, 99, '1')
    const secondIssue = buildIssue(2, 99, '2')
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    mockedIssuesApi.list.mockResolvedValue(buildListResponse([firstIssue, secondIssue]))
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: 99,
      issues: [emptyDependencies(firstIssue), emptyDependencies(secondIssue)],
    })
    mockedIssuesApi.markRead
      .mockImplementationOnce(() => firstToggle.promise)
      .mockResolvedValueOnce(undefined)

    render(<IssueList thread={buildThread(99)} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByText('#2'))
    await waitFor(() => {
      expect(mockedIssuesApi.markRead).toHaveBeenCalledTimes(2)
      expect(screen.getByText('#2').closest('.issue-item')).toHaveClass('read')
    })

    await act(async () => {
      firstToggle.reject(new Error('first toggle failed'))
      await firstToggle.promise.catch(() => undefined)
    })

    expect(screen.getByText('#1').closest('.issue-item')).toHaveClass('unread')
    expect(screen.getByText('#2').closest('.issue-item')).toHaveClass('read')
    errorSpy.mockRestore()
  })

  it('reinserts a filtered issue and restores the count when its toggle fails', async () => {
    const toggle = createDeferred<void>()
    const issue = buildIssue(1, 99, '1')
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    mockedIssuesApi.list.mockResolvedValue(buildListResponse([issue]))
    mockedIssuesApi.markRead.mockImplementationOnce(() => toggle.promise)

    render(<IssueList thread={buildThread(99)} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await userEvent.selectOptions(screen.getByRole('combobox'), 'unread')
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())

    await act(async () => {
      toggle.reject(new Error('toggle failed'))
      await toggle.promise.catch(() => undefined)
    })

    expect(screen.getByText('#1').closest('.issue-item')).toHaveClass('unread')
    expect(screen.getByText('Read 0 of 1 (0%)')).toBeInTheDocument()
    errorSpy.mockRestore()
  })

  it('preserves a newly appended page when an earlier toggle rolls back', async () => {
    const firstToggle = createDeferred<void>()
    const firstIssue = buildIssue(1, 99, '1')
    const secondIssue = buildIssue(2, 99, '2')
    const appendedIssue = buildIssue(3, 99, '3')
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse([firstIssue, secondIssue], 'page-2', 3))
      .mockResolvedValueOnce(buildListResponse([appendedIssue], null, 3))
    mockedIssuesApi.markRead.mockImplementationOnce(() => firstToggle.promise)

    render(<IssueList thread={buildThread(99)} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(1))
    await userEvent.click(screen.getByRole('button', { name: /load more/i }))
    await waitFor(() => expect(screen.getByText('#3')).toBeInTheDocument())

    await act(async () => {
      firstToggle.reject(new Error('toggle failed'))
      await firstToggle.promise.catch(() => undefined)
    })

    expect(screen.getByText('#1').closest('.issue-item')).toHaveClass('unread')
    expect(screen.getByText('#3')).toBeInTheDocument()
    errorSpy.mockRestore()
  })
})
