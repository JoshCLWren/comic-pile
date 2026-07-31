import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import { issueDependenciesApi } from '../services/api-dependencies'
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

function buildIssues(count: number): Issue[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    thread_id: 99,
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
  })
})
