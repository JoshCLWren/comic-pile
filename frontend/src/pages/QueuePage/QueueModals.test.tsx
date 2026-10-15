/**
 * @vitest-environment jsdom
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { vi } from 'vitest'

// Mock the API calls
vi.mock('../../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn().mockResolvedValue({
      issues: [
        { id: 1, issue_number: 1, status: 'unread', thread_id: 1 },
        { id: 2, issue_number: 2, status: 'read', thread_id: 1 },
      ],
      next_page_token: null,
    }),
  },
}))

// Mock the dependencies
vi.mock('../../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
  }),
}))

vi.mock('../../hooks/useQueueThreads', () => ({
  useQueueThreads: () => ({
    data: [
      {
        id: 1,
        title: 'Test Series',
        format: 'Comic',
        issues_remaining: null,
        total_issues: 6,
        notes: '',
        is_blocked: false,
      },
    ],
    isPending: false,
    isError: false,
    nextPageToken: null,
    loadMore: vi.fn(),
  }),
}))

vi.mock('../../hooks/useSession', () => ({
  useSession: () => ({
    data: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('../../hooks/useThread', () => ({
  useUpdateThread: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('../../hooks/useQueue', () => ({
  useMoveToPosition: () => vi.fn(),
  useQueueThreads: () => ({
    data: [],
    isPending: false,
    isError: false,
    nextPageToken: null,
    loadMore: vi.fn(),
  }),
  useShuffleQueue: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('../../hooks/useQueueBlockingInfo', () => ({
  useQueueBlockingInfo: () => ({
    blockingByThreadId: {},
  }),
}))

vi.mock('../../hooks/useQueueFilters', () => ({
  useQueueFilters: () => ({
    sortBy: 'position',
    setSortBy: vi.fn(),
  }),
}))

vi.mock('../../hooks/useQueueCrossovers', () => ({
  useQueueCrossovers: () => vi.fn(),
}))

vi.mock('../../hooks/useQueueThreadActions', () => ({
  useQueueThreadActions: () => ({
    requestDelete: vi.fn(),
    requestReposition: vi.fn(),
  }),
}))

vi.mock('../../components/snoozeAvailability', () => ({
  canSnoozeSeries: () => true,
}))

const mockQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
})

// Import after mocking
import QueuePage from './QueuePage'

describe('Edit Series Dialog Loading States', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state and disables Save button when opening Edit Series', async () => {
    // Render the component
    render(
      <QueryClientProvider client={mockQueryClient}>
        <BrowserRouter>
          <QueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    )

    // Find and click the Edit button for the test series
    const editButton = screen.getByText('Edit')
    fireEvent.click(editButton)

    // Verify the Edit Series dialog opens
    expect(screen.getByText('Edit Series')).toBeInTheDocument()

    // Verify loading state is shown
    expect(screen.getByText('Loading issues...')).toBeInTheDocument()

    // Verify Save button is disabled
    const saveButton = screen.getByRole('button', { name: /Save Changes/i })
    expect(saveButton).toBeDisabled()
    expect(saveButton).toHaveTextContent('Loading issues...')
  })

  it('enables Save button and removes loading state when issues load', async () => {
    // Render the component
    render(
      <QueryClientProvider client={mockQueryClient}>
        <BrowserRouter>
          <QueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    )

    // Find and click the Edit button for the test series
    const editButton = screen.getByText('Edit')
    fireEvent.click(editButton)

    // Wait for the issues to load
    await waitFor(() => {
      expect(screen.queryByText('Loading issues...')).not.toBeInTheDocument()
    })

    // Verify issues are displayed
    expect(screen.getByText('#1 🟢')).toBeInTheDocument()
    expect(screen.getByText('#2 ✅')).toBeInTheDocument()

    // Verify Save button is enabled
    const saveButton = screen.getByRole('button', { name: /Save Changes/i })
    expect(saveButton).toBeEnabled()
    expect(saveButton).toHaveTextContent('Save Changes')
  })

  it('sends exactly one request when Save is clicked after issues load', async () => {
    // Create a spy for the update mutation
    const updateSpy = vi.fn()
    vi.mocked('../../hooks/useThread').useUpdateThread.mockReturnValue({
      mutate: updateSpy,
      isPending: false,
    })

    // Render the component
    render(
      <QueryClientProvider client={mockQueryClient}>
        <BrowserRouter>
          <QueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    )

    // Find and click the Edit button for the test series
    const editButton = screen.getByText('Edit')
    fireEvent.click(editButton)

    // Wait for the issues to load
    await waitFor(() => {
      expect(screen.queryByText('Loading issues...')).not.toBeInTheDocument()
    })

    // Click Save button
    const saveButton = screen.getByRole('button', { name: /Save Changes/i })
    fireEvent.click(saveButton)

    // Verify exactly one request was sent
    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledTimes(1)
    })
  })

  it('handles error state when issues fail to load', async () => {
    // Mock the API to throw an error
    vi.mocked('../../services/api-issues').issuesApi.list.mockRejectedValue(
      new Error('Failed to load issues')
    )

    // Render the component
    render(
      <QueryClientProvider client={mockQueryClient}>
        <BrowserRouter>
          <QueuePage />
        </BrowserRouter>
      </QueryClientProvider>
    )

    // Find and click the Edit button for the test series
    const editButton = screen.getByText('Edit')
    fireEvent.click(editButton)

    // Wait for the error state
    await waitFor(() => {
      expect(screen.getByText('Loading issues...')).toBeInTheDocument()
    })

    // Verify Save button remains disabled
    const saveButton = screen.getByRole('button', { name: /Save Changes/i })
    expect(saveButton).toBeDisabled()
  })
})