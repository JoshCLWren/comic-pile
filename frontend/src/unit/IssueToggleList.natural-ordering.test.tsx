/**
 * Tests for IssueToggleList component with natural ordering
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IssueToggleList } from '../IssueToggleList'
import { issuesApi } from '../services/api-issues'

// Mock the issues API
jest.mock('../services/api-issues', () => ({
  issuesApi: {
    create: jest.fn(),
    list: jest.fn(),
    markRead: jest.fn(),
    markUnread: jest.fn(),
    delete: jest.fn(),
    reorder: jest.fn(),
  }
}))

const mockIssues = [
  { id: 1, thread_id: 1, issue_number: '33', position: 1, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
  { id: 2, thread_id: 1, issue_number: '34', position: 2, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
  { id: 3, thread_id: 1, issue_number: '35', position: 3, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
]

const mockThreadIssuesResponse = {
  issues: mockIssues,
  total_count: 3,
  page_size: 50,
  next_page_token: null,
}

describe('IssueToggleList with Natural Ordering', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false }
      }
    })
    jest.clearAllMocks()
    
    // Mock the list API to return existing issues
    issuesApi.list.mockResolvedValue(mockThreadIssuesResponse)
  })

  test('adds issue #2 to #33,#34,#35 at the beginning', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <IssueToggleList threadId={1} />
      </QueryClientProvider>
    )

    // Wait for issues to load
    await waitFor(() => {
      screen.getByText('Issues')
    })

    // Find the add input and button
    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    // Add issue #2
    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(addButton)

    // Verify the API was called with correct parameters
    await waitFor(() => {
      expect(issuesApi.create).toHaveBeenCalledWith(1, '2', {
        insert_after_issue_id: null // Should insert at beginning
      })
    })
  })

  test('adds issue #2 to #1,#3 after issue #1', async () => {
    // Mock different existing issues
    const differentMockIssues = [
      { id: 1, thread_id: 1, issue_number: '1', position: 1, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
      { id: 2, thread_id: 1, issue_number: '3', position: 2, status: 'unread', read_at: null, created_at: '2023-01-01T00:00:00Z' },
    ]
    
    issuesApi.list.mockResolvedValue({
      ...mockThreadIssuesResponse,
      issues: differentMockIssues
    })

    render(
      <QueryClientProvider client={queryClient}>
        <IssueToggleList threadId={1} />
      </QueryClientProvider>
    )

    // Wait for issues to load
    await waitFor(() => {
      screen.getByText('Issues')
    })

    // Find the add input and button
    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    // Add issue #2
    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(addButton)

    // Verify the API was called with correct parameters
    await waitFor(() => {
      expect(issuesApi.create).toHaveBeenCalledWith(1, '2', {
        insert_after_issue_id: 1 // Should insert after issue #1
      })
    })
  })

  test('adds multiple issues in natural order', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <IssueToggleList threadId={1} />
      </QueryClientProvider>
    )

    // Wait for issues to load
    await waitFor(() => {
      screen.getByText('Issues')
    })

    // Find the add input and button
    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    // Add multiple issues
    fireEvent.change(input, { target: { value: '2,4' } })
    fireEvent.click(addButton)

    // Verify the API was called with correct parameters
    await waitFor(() => {
      expect(issuesApi.create).toHaveBeenCalledWith(1, '2,4', {
        insert_after_issue_id: null // Should insert at beginning since 2 < 33
      })
    })
  })

  test('adds non-numeric issue (should append)', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <IssueToggleList threadId={1} />
      </QueryClientProvider>
    )

    // Wait for issues to load
    await waitFor(() => {
      screen.getByText('Issues')
    })

    // Find the add input and button
    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    // Add non-numeric issue
    fireEvent.change(input, { target: { value: 'Annual 1' } })
    fireEvent.click(addButton)

    // Verify the API was called with append (null for insert_after_issue_id)
    await waitFor(() => {
      expect(issuesApi.create).toHaveBeenCalledWith(1, 'Annual 1', {
        insert_after_issue_id: null // Should append for ambiguous cases
      })
    })
  })

  test('handles empty input gracefully', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <IssueToggleList threadId={1} />
      </QueryClientProvider>
    )

    // Wait for issues to load
    await waitFor(() => {
      screen.getByText('Issues')
    })

    // Find the add input and button
    const input = screen.getByPlaceholderText('Add: 19-24 or 0, Annual 1')
    const addButton = screen.getByText('Add')

    // Try to add empty input
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(addButton)

    // Verify the API was not called
    expect(issuesApi.create).not.toHaveBeenCalled()
  })
})