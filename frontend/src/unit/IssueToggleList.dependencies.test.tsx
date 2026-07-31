import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import {
  issueDependenciesApi,
  type ThreadIssueDependenciesResponse,
} from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

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
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, resolve, reject }
}

function buildIssues(count: number, threadId = 99, idOffset = 0): Issue[] {
  return Array.from({ length: count }, (_, index) => ({
    id: idOffset + index + 1,
    thread_id: threadId,
    issue_number: String(index + 1),
    status: 'unread' as const,
    read_at: null,
    created_at: '2026-07-31T00:00:00Z',
  }))
}

function buildListResponse(issues: Issue[]): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
  }
}

describe('IssueToggleList dependency loading', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(buildIssues(40)))
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: 99,
      issues: [
        {
          issue_id: 1,
          incoming: [],
          outgoing: [
            {
              dependency_id: 501,
              source_issue_id: 1,
              source_issue_number: '1',
              source_thread_id: 99,
              source_thread_title: 'Production Profile',
            },
          ],
        },
        {
          issue_id: 2,
          incoming: [],
          outgoing: [],
        },
      ],
    })
  })

  it('loads dependencies once for the thread instead of once per issue', async () => {
    render(<IssueToggleList threadId={99} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Show all 40' })).toBeInTheDocument()
    })

    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledWith(99)
    expect(
      screen.getByRole('button', { name: 'View dependencies for issue #1' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'View dependencies for issue #2' }),
    ).not.toBeInTheDocument()
  })

  it('ignores issue results from a superseded thread load', async () => {
    const oldIssues = createDeferred<IssueListResponse>()
    mockedIssuesApi.list.mockImplementation((threadId) => {
      if (threadId === 1) {
        return oldIssues.promise
      }

      return Promise.resolve(buildListResponse(buildIssues(1, 2, 100)))
    })
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({ thread_id: 2, issues: [] })

    const { rerender } = render(<IssueToggleList threadId={1} />)
    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledWith(1, { page_size: 100 })
    })

    rerender(<IssueToggleList threadId={2} />)
    await waitFor(() => {
      expect(screen.getByTestId('issue-toggle-101')).toBeInTheDocument()
    })

    await act(async () => {
      oldIssues.resolve(buildListResponse(buildIssues(1, 1)))
      await oldIssues.promise
    })

    expect(screen.getByTestId('issue-toggle-101')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-toggle-1')).not.toBeInTheDocument()
    expect(mockedIssueDependenciesApi.listForThread).not.toHaveBeenCalledWith(1)
  })

  it('ignores dependency results from a superseded thread load', async () => {
    const oldDependencies = createDeferred<ThreadIssueDependenciesResponse>()
    mockedIssuesApi.list.mockImplementation((threadId) =>
      Promise.resolve(buildListResponse(buildIssues(1, threadId, threadId * 100))))
    mockedIssueDependenciesApi.listForThread.mockImplementation((threadId) => {
      if (threadId === 1) {
        return oldDependencies.promise
      }

      return Promise.resolve({
        thread_id: 2,
        issues: [
          {
            issue_id: 201,
            incoming: [],
            outgoing: [
              {
                dependency_id: 602,
                source_issue_id: 201,
                source_issue_number: '1',
                source_thread_id: 2,
                source_thread_title: 'New Thread',
              },
            ],
          },
        ],
      })
    })

    const { rerender } = render(<IssueToggleList threadId={1} />)
    await waitFor(() => {
      expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledWith(1)
    })

    rerender(<IssueToggleList threadId={2} />)
    await waitFor(() => {
      expect(screen.getByTestId('issue-toggle-201')).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'View dependencies for issue #1' }),
      ).toBeInTheDocument()
    })

    await act(async () => {
      oldDependencies.resolve({
        thread_id: 1,
        issues: [
          {
            issue_id: 101,
            incoming: [],
            outgoing: [
              {
                dependency_id: 601,
                source_issue_id: 101,
                source_issue_number: '1',
                source_thread_id: 1,
                source_thread_title: 'Old Thread',
              },
            ],
          },
        ],
      })
      await oldDependencies.promise
    })

    expect(screen.getByTestId('issue-toggle-201')).toBeInTheDocument()
    expect(screen.queryByTestId('issue-toggle-101')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'View dependencies for issue #1' }),
    ).toBeInTheDocument()
  })
})
