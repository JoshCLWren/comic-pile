import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
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

const BASE_ISSUES: Issue[] = [
  {
    id: 1,
    thread_id: 99,
    issue_number: '1',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
  {
    id: 2,
    thread_id: 99,
    issue_number: '2',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
]

const buildListResponse = (
  issues: Issue[] = BASE_ISSUES,
  nextPageToken: string | null = null,
  totalCount?: number,
): IssueListResponse => ({
  issues,
  total_count: totalCount ?? issues.length,
  page_size: 50,
  next_page_token: nextPageToken,
})

const emptyDependencies = (issue: Issue): IssueDependenciesResponse => ({
  issue_id: issue.id,
  incoming: [],
  outgoing: [],
})

const mockThread: Thread = {
  id: 99,
  title: 'Test Thread',
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
}

describe('IssueList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: mockThread.id,
      issues: BASE_ISSUES.map(emptyDependencies),
    })
  })

  it('loads issues and dependencies once per thread', async () => {
    mockedIssuesApi.list.mockResolvedValueOnce(buildListResponse())

    render(
      <BrowserRouter>
        <IssueList thread={mockThread} />
      </BrowserRouter>,
    )

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
      expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
    })
    expect(mockedIssuesApi.list).toHaveBeenCalledWith(mockThread.id, {
      page_size: 50,
      status: undefined,
    })
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledWith(mockThread.id)
  })

  it('loads another issue page without refetching thread dependencies', async () => {
    const firstPage = buildListResponse(BASE_ISSUES, 'page-2', 4)
    const secondPage = buildListResponse([
      {
        id: 3,
        thread_id: 99,
        issue_number: '3',
        status: 'unread',
        read_at: null,
        created_at: '2026-03-08T00:00:00Z',
      },
      {
        id: 4,
        thread_id: 99,
        issue_number: '4',
        status: 'unread',
        read_at: null,
        created_at: '2026-03-08T00:00:00Z',
      },
    ])

    mockedIssuesApi.list
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)

    render(
      <BrowserRouter>
        <IssueList thread={mockThread} />
      </BrowserRouter>,
    )

    await waitFor(() => expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('button', { name: /load more/i }))

    await waitFor(() => expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2))
    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(2, mockThread.id, {
      page_size: 50,
      status: undefined,
      page_token: 'page-2',
    })
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
  })

  it('handles filter changes with a fresh issue fetch only', async () => {
    const filteredIssue: Issue = {
      ...BASE_ISSUES[1],
      status: 'read',
      read_at: '2026-03-08T00:00:00Z',
    }
    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse(BASE_ISSUES))
      .mockResolvedValueOnce(buildListResponse([filteredIssue]))

    render(
      <BrowserRouter>
        <IssueList thread={mockThread} />
      </BrowserRouter>,
    )

    await waitFor(() => expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1))
    await userEvent.selectOptions(screen.getByRole('combobox'), 'read')

    await waitFor(() => expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2))
    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(2, mockThread.id, {
      page_size: 50,
      status: 'read',
    })
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
  })

  it('renders empty and loading failures without crashing', async () => {
    mockedIssuesApi.list.mockResolvedValueOnce(buildListResponse([]))
    const { rerender } = render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())

    mockedIssuesApi.list.mockRejectedValueOnce(new Error('load failed'))
    mockedIssueDependenciesApi.listForThread.mockResolvedValueOnce({
      thread_id: 100,
      issues: [],
    })
    rerender(<IssueList thread={{ ...mockThread, id: 100 }} />)
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())
  })

  it('toggles local status without reloading issues or dependencies', async () => {
    const onThreadUpdated = vi.fn()
    const readIssue: Issue = {
      ...BASE_ISSUES[0],
      status: 'read',
      read_at: '2026-03-09T00:00:00Z',
    }
    const unreadIssue = { ...BASE_ISSUES[1], id: 3 }
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([readIssue, unreadIssue]))
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: mockThread.id,
      issues: [
        {
          issue_id: readIssue.id,
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
        emptyDependencies(unreadIssue),
      ],
    })
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)
    mockedIssuesApi.markRead.mockResolvedValue(undefined)

    render(
      <IssueList
        thread={{ ...mockThread, next_unread_issue_id: 3 }}
        onThreadUpdated={onThreadUpdated}
      />,
    )

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByTitle('Has dependencies')).toBeInTheDocument()
    await userEvent.click(screen.getByTitle('Has dependencies'))
    expect(mockedIssuesApi.markUnread).not.toHaveBeenCalled()

    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(1))
    expect(onThreadUpdated).toHaveBeenCalledWith(99)

    await userEvent.click(screen.getByText('#2'))
    await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(3))
    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
  })

  it('rolls back an optimistic status toggle when the request fails', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(BASE_ISSUES))
    mockedIssuesApi.markRead.mockRejectedValueOnce(new Error('toggle failed'))

    render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    await userEvent.click(screen.getByText('#1'))

    await waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        'Failed to toggle issue status:',
        expect.any(Error),
      )
      expect(screen.getByText('#1').closest('.issue-item')).toHaveClass('unread')
    })
    errorSpy.mockRestore()
  })

  it('removes a toggled issue from a filtered list without refetching', async () => {
    const readIssue: Issue = {
      ...BASE_ISSUES[0],
      status: 'read',
      read_at: '2026-03-10T00:00:00Z',
    }
    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse(BASE_ISSUES))
      .mockResolvedValueOnce(buildListResponse([readIssue], null, 1))
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)

    render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByRole('combobox'), 'read')
    await waitFor(() => expect(screen.getByText(/Read 1 of 1 \(100%\)/)).toBeInTheDocument())

    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())
    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2)
    expect(mockedIssueDependenciesApi.listForThread).toHaveBeenCalledTimes(1)
  })

  it('renders outgoing dependencies and read dates without a callback', async () => {
    const readIssue: Issue = {
      ...BASE_ISSUES[0],
      status: 'read',
      read_at: '2026-03-10T00:00:00Z',
    }
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([readIssue], null, 1))
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: mockThread.id,
      issues: [
        {
          issue_id: readIssue.id,
          incoming: [],
          outgoing: [
            {
              dependency_id: 3,
              source_issue_id: 4,
              source_issue_number: '4',
              source_thread_id: 5,
              source_thread_title: 'Next',
            },
          ],
        },
      ],
    })
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)

    render(<IssueList thread={{ ...mockThread, next_unread_issue_id: 999 }} />)

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByText(/Read 1 of 1 \(100%\)/)).toBeInTheDocument()
    expect(screen.getByTitle('Has dependencies')).toBeInTheDocument()
    await userEvent.click(screen.getByText('#1'))
    expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(1)
  })

  it('clears stale dependency indicators when the thread changes', async () => {
    const issue = BASE_ISSUES[0]
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([issue]))
    mockedIssueDependenciesApi.listForThread
      .mockResolvedValueOnce({
        thread_id: mockThread.id,
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
      .mockResolvedValueOnce({ thread_id: 100, issues: [emptyDependencies(issue)] })

    const { rerender } = render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByTitle('Has dependencies')).toBeInTheDocument())

    rerender(<IssueList thread={{ ...mockThread, id: 100 }} />)
    await waitFor(() => expect(screen.queryByTitle('Has dependencies')).not.toBeInTheDocument())
  })

  it('keeps issues usable when batched dependency loading fails', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(BASE_ISSUES))
    mockedIssueDependenciesApi.listForThread.mockRejectedValueOnce(new Error('dependency failed'))

    render(<IssueList thread={mockThread} />)

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.queryByTitle('Has dependencies')).not.toBeInTheDocument()
    expect(errorSpy).toHaveBeenCalledWith(
      `Failed to load dependencies for thread ${mockThread.id}:`,
      expect.any(Error),
    )
    errorSpy.mockRestore()
  })
})
