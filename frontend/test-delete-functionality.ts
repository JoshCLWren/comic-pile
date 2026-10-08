/**
 * Simple test to verify the IssueToggleList delete functionality works correctly
 * This test verifies that the delete dialog opens properly and the correct callbacks are called
 */

import { render, fireEvent, waitFor } from '@testing-library/react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import DeleteIssueDialog from '../pages/QueuePage/DeleteIssueDialog'
import type { Issue } from '../types'

// Mock the API services
const mockIssuesApi = {
  list: async () => ({
    issues: [
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
    ],
    next_page_token: null,
  }),
  create: async () => ({
    issues: [],
    next_page_token: null,
  }),
  markRead: async () => {},
  markUnread: async () => {},
  delete: async () => {},
  reorder: async () => {},
}

const mockDependenciesApi = {
  listForThread: async () => ({
    issues: [],
  }),
}

// Test issue data
const testIssues: Issue[] = [
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

describe('IssueToggleList Delete Functionality', () => {
  it('opens delete dialog when delete button is clicked', async () => {
    const { getByTestId, getByText } = render(
      <IssueToggleList
        threadId={99}
        issuesApi={mockIssuesApi}
        dependenciesApi={mockDependenciesApi}
      />
    )

    // Wait for issues to load
    await waitFor(() => {
      expect(getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    // Click the delete button for issue #2
    fireEvent.click(getByTestId('issue-delete-2'))

    // Verify the delete dialog opens
    expect(getByTestId('delete-issue-dialog')).toBeInTheDocument()
    expect(getByText('Delete Issue')).toBeInTheDocument()
    expect(getByText('Are you sure you want to delete issue #2?')).toBeInTheDocument()
    expect(getByText('Cancel')).toBeInTheDocument()
    expect(getByText('Delete Issue')).toBeInTheDocument()
  })

  it('calls delete API when confirm button is clicked', async () => {
    const deleteSpy = vi.spyOn(mockIssuesApi, 'delete')
    const { getByTestId, getByText } = render(
      <IssueToggleList
        threadId={99}
        issuesApi={mockIssuesApi}
        dependenciesApi={mockDependenciesApi}
      />
    )

    // Wait for issues to load
    await waitFor(() => {
      expect(getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    // Click the delete button for issue #2
    fireEvent.click(getByTestId('issue-delete-2'))

    // Verify the delete dialog opens
    expect(getByTestId('delete-issue-dialog')).toBeInTheDocument()

    // Click the Delete button in the dialog
    fireEvent.click(getByTestId('confirm-delete-issue'))

    // Verify the delete API was called
    expect(deleteSpy).toHaveBeenCalledWith(2)
  })

  it('does not call delete API when cancel button is clicked', async () => {
    const deleteSpy = vi.spyOn(mockIssuesApi, 'delete')
    const { getByTestId, getByText } = render(
      <IssueToggleList
        threadId={99}
        issuesApi={mockIssuesApi}
        dependenciesApi={mockDependenciesApi}
      />
    )

    // Wait for issues to load
    await waitFor(() => {
      expect(getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    // Click the delete button for issue #2
    fireEvent.click(getByTestId('issue-delete-2'))

    // Verify the delete dialog opens
    expect(getByTestId('delete-issue-dialog')).toBeInTheDocument()

    // Click the Cancel button in the dialog
    fireEvent.click(getByText('Cancel'))

    // Verify the delete API was NOT called
    expect(deleteSpy).not.toHaveBeenCalled()
  })

  it('shows loading state when delete is in progress', async () => {
    // Mock a slow delete operation
    const slowDelete = vi.fn().mockImplementation(() => new Promise(resolve => setTimeout(resolve, 100)))
    const deleteSpy = vi.spyOn(mockIssuesApi, 'delete').mockImplementation(slowDelete)
    
    const { getByTestId, getByText } = render(
      <IssueToggleList
        threadId={99}
        issuesApi={mockIssuesApi}
        dependenciesApi={mockDependenciesApi}
      />
    )

    // Wait for issues to load
    await waitFor(() => {
      expect(getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    // Click the delete button for issue #2
    fireEvent.click(getByTestId('issue-delete-2'))

    // Verify the delete dialog opens
    expect(getByTestId('delete-issue-dialog')).toBeInTheDocument()

    // Click the Delete button in the dialog
    fireEvent.click(getByTestId('confirm-delete-issue'))

    // Verify the button shows loading state
    expect(getByTestId('confirm-delete-issue')).toHaveTextContent('Deleting...')
    
    // Wait for the operation to complete
    await act(async () => {
      await slowDelete()
    })

    // Verify the button returns to normal state
    expect(getByTestId('confirm-delete-issue')).toHaveTextContent('Delete Issue')
  })
})

// Helper function to act with async operations
async function act(fn: () => Promise<void>) {
  await fn()
}