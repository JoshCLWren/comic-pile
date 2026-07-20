import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { IssueList } from '../components/IssueList'
import { issuesApi } from '../services/api-issues'
import { dependenciesApi } from '../services/api'
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

vi.mock('../services/api', () => ({
  dependenciesApi: {
    getIssueDependencies: vi.fn(),
  },
}))

const mockedIssuesApi = vi.mocked(issuesApi, { deep: true })
const mockedDependenciesApi = vi.mocked(dependenciesApi, { deep: true })

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
  totalCount?: number
): IssueListResponse => ({
  issues,
  total_count: totalCount ?? issues.length,
  page_size: 50,
  next_page_token: nextPageToken,
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
  collection_id: null,
  created_at: '2026-03-08T00:00:00Z',
  next_unread_issue_id: null,
  next_unread_issue_number: null,
}

describe('IssueList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedDependenciesApi.getIssueDependencies.mockResolvedValue({
      issue_id: 99,
      incoming: [],
      outgoing: [],
    } satisfies IssueDependenciesResponse)
  })

  it('calls issuesApi.list once on mount', async () => {
    mockedIssuesApi.list.mockResolvedValueOnce(buildListResponse())

    render(
      <BrowserRouter>
        <IssueList thread={mockThread} />
      </BrowserRouter>
    )

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
    })
    expect(mockedIssuesApi.list).toHaveBeenCalledWith(mockThread.id, {
      page_size: 50,
      status: undefined,
    })
  })

  it('calls issuesApi.list again when "Load more" is clicked', async () => {
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
      </BrowserRouter>
    )

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
    })

    const loadMoreButton = screen.getByRole('button', { name: /load more/i })
    await userEvent.click(loadMoreButton)

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2)
    })
    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(2, mockThread.id, {
      page_size: 50,
      status: undefined,
      page_token: 'page-2',
    })
  })

  it('handles filter changes with fresh fetch', async () => {
    const firstPage = buildListResponse(BASE_ISSUES, null, 2)
    const filteredPage = buildListResponse([
      {
        id: 2,
        thread_id: 99,
        issue_number: '2',
        status: 'read',
        read_at: '2026-03-08T00:00:00Z',
        created_at: '2026-03-08T00:00:00Z',
      },
    ])

    mockedIssuesApi.list
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(filteredPage)

    render(
      <BrowserRouter>
        <IssueList thread={mockThread} />
      </BrowserRouter>
    )

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(1)
    })

    const filterSelect = screen.getByRole('combobox')
    await userEvent.selectOptions(filterSelect, 'read')

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2)
    })
    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(2, mockThread.id, {
      page_size: 50,
      status: 'read',
    })
  })

  it('renders empty and loading failures without crashing', async () => {
    mockedIssuesApi.list.mockResolvedValueOnce(buildListResponse([]))
    const { rerender } = render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())

    mockedIssuesApi.list.mockRejectedValueOnce(new Error('load failed'))
    rerender(<IssueList thread={{ ...mockThread, id: 100 }} />)
    await waitFor(() => expect(screen.getByText('No issues found')).toBeInTheDocument())
  })

  it('toggles read and unread issues, shows dependencies, and handles dependency errors', async () => {
    const onThreadUpdated = vi.fn()
    const readIssue = { ...BASE_ISSUES[0], status: 'read' as const, read_at: '2026-03-09T00:00:00Z' }
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([readIssue, { ...BASE_ISSUES[1], id: 3 }]))
    mockedDependenciesApi.getIssueDependencies
      .mockResolvedValueOnce({ issue_id: 1, incoming: [{ dependency_id: 2, source_issue_id: 2, source_issue_number: '2', source_thread_id: 20, source_thread_title: 'Source' }], outgoing: [] })
      .mockRejectedValueOnce(new Error('dependency failed'))
    mockedIssuesApi.markUnread.mockResolvedValue(undefined)
    mockedIssuesApi.markRead.mockResolvedValue(undefined)
    render(<IssueList thread={{ ...mockThread, next_unread_issue_id: 3 }} onThreadUpdated={onThreadUpdated} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByTitle('Has dependencies')).toBeInTheDocument()
    await userEvent.click(screen.getByTitle('Has dependencies'))
    expect(mockedIssuesApi.markUnread).not.toHaveBeenCalled()
    const items = screen.getAllByText(/#\d/)
    await userEvent.click(items[0]!)
    expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(1)
    await waitFor(() => expect(onThreadUpdated).toHaveBeenCalledWith(99))
    await userEvent.click(screen.getByText('#2'))
    expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(3)
  })

  it('keeps the list usable when a status toggle fails', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(BASE_ISSUES))
    mockedIssuesApi.markRead.mockRejectedValueOnce(new Error('toggle failed'))
    render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    await userEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Failed to toggle issue status:', expect.any(Error)))
    errorSpy.mockRestore()
  })

  it('handles zero-count progress, outgoing dependencies, and read dates without a callback', async () => {
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([
      { ...BASE_ISSUES[0], status: 'read', read_at: '2026-03-10T00:00:00Z' },
    ], null, 1))
    mockedDependenciesApi.getIssueDependencies.mockResolvedValue({
      issue_id: 1,
      incoming: [],
      outgoing: [{ dependency_id: 3, source_issue_id: 4, source_issue_number: '4', source_thread_id: 5, source_thread_title: 'Next' }],
    })

    render(<IssueList thread={{ ...mockThread, next_unread_issue_id: 999 }} />)

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByText(/Read 1 of 1 \(100%\)/)).toBeInTheDocument()
    expect(screen.getByTitle('Has dependencies')).toBeInTheDocument()
    await userEvent.click(screen.getByText('#1'))
    expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(1)
  })

  it('removes stale dependency indicators when a later response is empty', async () => {
    const issue = BASE_ISSUES[0]
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([issue]))
    mockedDependenciesApi.getIssueDependencies.mockResolvedValueOnce({
      issue_id: issue.id,
      incoming: [{ dependency_id: 2, source_issue_id: 2, source_issue_number: '2', source_thread_id: 20, source_thread_title: 'Source' }],
      outgoing: [],
    }).mockResolvedValueOnce({ issue_id: issue.id, incoming: [], outgoing: [] })
    const { rerender } = render(<IssueList thread={mockThread} />)
    await waitFor(() => expect(screen.getByTitle('Has dependencies')).toBeInTheDocument())
    rerender(<IssueList thread={{ ...mockThread, id: 100 }} />)
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([issue]))
    await waitFor(() => expect(screen.queryByTitle('Has dependencies')).not.toBeInTheDocument())
  })
})
