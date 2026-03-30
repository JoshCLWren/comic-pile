import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { IssueList } from '../components/IssueList'
import { issuesApi } from '../services/api-issues'
import { dependenciesApi } from '../services/api'
import type { Issue, IssueListResponse, Thread } from '../types'

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
  queue_position: 1,
  status: 'active',
  created_at: '2026-03-08T00:00:00Z',
  updated_at: '2026-03-08T00:00:00Z',
  last_rating: null,
  snoozed_until: null,
  next_unread_issue_id: null,
}

describe('IssueList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedDependenciesApi.getIssueDependencies.mockResolvedValue({ incoming: [], outgoing: [] } as IssueDependenciesResponse)
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
})
