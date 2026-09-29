/**
 * Tests for IssueToggleList component with natural ordering
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type { IssueToggleListApi, IssueToggleListDependenciesApi } from '../pages/QueuePage/IssueToggleList'
import type { Issue, IssueListResponse } from '../types'

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

const mockIssues: Issue[] = [
  { id: 1, thread_id: 1, issue_number: '33', position: 1, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
  { id: 2, thread_id: 1, issue_number: '34', position: 2, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
  { id: 3, thread_id: 1, issue_number: '35', position: 3, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
]

function buildListResponse(issues: Issue[]): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 50,
    next_page_token: null,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(buildListResponse(mockIssues))
  mockedIssuesApi.create.mockResolvedValue(buildListResponse([]))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssueDependenciesApi.listForThread.mockResolvedValue({ thread_id: 1, issues: [] })
})

describe('IssueToggleList with Natural Ordering', () => {
  it('adds issue #2 to #33,#34,#35 at the beginning', async () => {
    render(<IssueToggleList threadId={1} issuesApi={mockedIssuesApi} dependenciesApi={mockedIssueDependenciesApi} />)

    await waitFor(() => {
      screen.getByText('Issues')
    })

    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(addButton)

    await waitFor(() => {
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2', {
        insert_after_issue_id: null,
      })
    })
  })

  it('adds issue #2 to #1,#3 after issue #1', async () => {
    const differentMockIssues: Issue[] = [
      { id: 1, thread_id: 1, issue_number: '1', position: 1, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
      { id: 2, thread_id: 1, issue_number: '3', position: 2, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
    ]
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(differentMockIssues))

    render(<IssueToggleList threadId={1} issuesApi={mockedIssuesApi} dependenciesApi={mockedIssueDependenciesApi} />)

    await waitFor(() => {
      screen.getByText('Issues')
    })

    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(addButton)

    await waitFor(() => {
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2', {
        insert_after_issue_id: 1,
      })
    })
  })

  it('adds multiple issues in natural order', async () => {
    render(<IssueToggleList threadId={1} issuesApi={mockedIssuesApi} dependenciesApi={mockedIssueDependenciesApi} />)

    await waitFor(() => {
      screen.getByText('Issues')
    })

    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    fireEvent.change(input, { target: { value: '2,4' } })
    fireEvent.click(addButton)

    await waitFor(() => {
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, '2,4', {
        insert_after_issue_id: null,
      })
    })
  })

  it('adds non-numeric issue (should append at end)', async () => {
    render(<IssueToggleList threadId={1} issuesApi={mockedIssuesApi} dependenciesApi={mockedIssueDependenciesApi} />)

    await waitFor(() => {
      screen.getByText('Issues')
    })

    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    fireEvent.change(input, { target: { value: 'Annual 1' } })
    fireEvent.click(addButton)

    await waitFor(() => {
      expect(mockedIssuesApi.create).toHaveBeenCalledWith(1, 'Annual 1', {
        insert_after_issue_id: 3,
      })
    })
  })

  it('handles empty input gracefully', async () => {
    render(<IssueToggleList threadId={1} issuesApi={mockedIssuesApi} dependenciesApi={mockedIssueDependenciesApi} />)

    await waitFor(() => {
      screen.getByText('Issues')
    })

    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(addButton)

    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
  })
})
