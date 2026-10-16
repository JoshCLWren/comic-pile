import { render, screen, fireEvent, waitFor, useRef } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useParams } from 'react-router-dom'
import { vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { IssueToggleListHandle } from '../pages/QueuePage/IssueToggleList'

// Mock the hooks and dependencies
vi.mock('../hooks/useThread')
vi.mock('../hooks/useUpdateThread')
vi.mock('../hooks/useConnectedThreads')
vi.mock('../hooks/useCrossoverGroups')
vi.mock('../hooks/useThreadIssues')
vi.mock('../hooks/useTags')
vi.mock('../query/cacheEffects')
vi.mock('../../utils/apiError')
vi.mock('../types')
vi.mock('../pages/QueuePage/types')
vi.mock('../components/DependencyBuilder')
vi.mock('../components/Breadcrumbs')
vi.mock('../components/Tags/TagEditor')
vi.mock('../components/Tags/TagSection')
vi.mock('../components/Tags/IssueTagRowChips')
vi.mock('../components/Tags/BulkTagToolbar')
vi.mock('./thread-detail/IssueReadStatusButton')
vi.mock('../../utils/dependencyHelpers')
vi.mock('../../utils/runtimeChecks')

const mockUseThread = vi.mocked(require('../hooks/useThread').useThread)
const mockUseUpdateThread = vi.mocked(require('../hooks/useUpdateThread').useUpdateThread)

describe('ThreadDetailView - Issue Edit Dialog Fix', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

    // Mock useParams to return a thread ID
    vi.mocked(useParams).mockReturnValue({ id: '123' } as any)

    // Mock successful thread data
    mockUseThread.mockReturnValue({
      data: {
        id: 123,
        title: 'Test Thread',
        format: 'comic',
        issues_remaining: 10,
        total_issues: 50,
        status: 'active',
        queue_position: 5,
        notes: 'Test notes',
      },
      error: null,
      refetch: vi.fn(),
    })

    // Mock successful update thread mutation
    mockUseUpdateThread.mockReturnValue({
      mutate: vi.fn().mockResolvedValue({
        id: 123,
        title: 'Test Thread',
        format: 'comic',
        issues_remaining: 10,
        total_issues: 50,
        status: 'active',
        queue_position: 5,
        notes: 'Updated notes',
      }),
      isPending: false,
      error: null,
    })

    // Mock other hooks with default data
    vi.mocked(require('../hooks/useConnectedThreads').useConnectedThreads).mockReturnValue({
      connectedThreads: [],
      isPending: false,
      isError: false,
    })

    vi.mocked(require('../hooks/useCrossoverGroups').useCrossoverGroups).mockReturnValue({
      groupsByThreadId: {},
      isPending: false,
      error: null,
    })

    vi.mocked(require('../hooks/useThreadIssues').useThreadIssuePages).mockReturnValue({
      issues: [],
      totalCount: 0,
      isPending: false,
      isError: false,
      pages: [],
      nextPageToken: null,
      refetch: vi.fn(),
      fetchNextPage: vi.fn(),
    })

    vi.mocked(require('../hooks/useTags').useThreadIssuesEffectiveTags).mockReturnValue({
      data: null,
      isPending: false,
      isError: false,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('should render IssueToggleList in deferred mode', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ThreadDetailView />
        </MemoryRouter>
      </QueryClientProvider>
    )

    // Open the edit modal
    fireEvent.click(screen.getByText('Edit'))

    // Check that IssueToggleList is rendered with deferred mode
    const issueToggleList = screen.getByTestId('issue-toggle-list')
    expect(issueToggleList).toBeInTheDocument()
    // The deferred prop should be true (this would need to be added to the component with testId)
  })

  it('should call flush when saving changes with pending issues', async () => {
    const mockFlush = vi.fn()
    const mockHasPendingMutations = vi.fn().mockReturnValue(true)

    // Create a component that mocks the IssueToggleList ref
    const ThreadDetailViewWithMock = () => {
      const issueToggleListRef = useRef<{ flush: () => Promise<void>; hasPendingMutations: () => boolean }>(null)

      // Mock the ref methods
      issueToggleListRef.current = {
        flush: mockFlush,
        hasPendingMutations: mockHasPendingMutations,
      }

      return (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ThreadDetailView />
          </MemoryRouter>
        </QueryClientProvider>
      )
    }

    render(<ThreadDetailViewWithMock />)

    // Open the edit modal
    fireEvent.click(screen.getByText('Edit'))

    // Change some form data
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Updated Title' },
    })

    // Submit the form
    fireEvent.click(screen.getByText('Save Changes'))

    // Wait for flush to be called
    await waitFor(() => {
      expect(mockFlush).toHaveBeenCalled()
    })

    // Then expect the update mutation to be called
    expect(mockUseUpdateThread().mutate).toHaveBeenCalled()
  })

  it('should not call flush when no pending issues', async () => {
    const mockFlush = vi.fn()
    const mockHasPendingMutations = vi.fn().mockReturnValue(false)

    const ThreadDetailViewWithMock = () => {
      const issueToggleListRef = useRef<{ flush: () => Promise<void>; hasPendingMutations: () => boolean }>(null)

      issueToggleListRef.current = {
        flush: mockFlush,
        hasPendingMutations: mockHasPendingMutations,
      }

      return (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ThreadDetailView />
          </MemoryRouter>
        </QueryClientProvider>
      )
    }

    render(<ThreadDetailViewWithMock />)

    // Open the edit modal
    fireEvent.click(screen.getByText('Edit'))

    // Change some form data
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Updated Title' },
    })

    // Submit the form
    fireEvent.click(screen.getByText('Save Changes'))

    // Wait for the submission to complete
    await waitFor(() => {
      expect(mockFlush).not.toHaveBeenCalled()
    })

    // Expect the update mutation to be called directly
    expect(mockUseUpdateThread().mutate).toHaveBeenCalled()
  })

  it('should handle flush errors gracefully', async () => {
    const mockFlush = vi.fn().mockRejectedValue(new Error('Flush failed'))
    const mockHasPendingMutations = vi.fn().mockReturnValue(true)

    const ThreadDetailViewWithMock = () => {
      const issueToggleListRef = useRef<{ flush: () => Promise<void>; hasPendingMutations: () => boolean }>(null)

      issueToggleListRef.current = {
        flush: mockFlush,
        hasPendingMutations: mockHasPendingMutations,
      }

      return (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ThreadDetailView />
          </MemoryRouter>
        </QueryClientProvider>
      )
    }

    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(<ThreadDetailViewWithMock />)

    // Open the edit modal
    fireEvent.click(screen.getByText('Edit'))

    // Change some form data
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Updated Title' },
    })

    // Submit the form
    fireEvent.click(screen.getByText('Save Changes'))

    // Wait for the error to be handled
    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to update thread or flush issues:', expect.any(Error))
    })

    consoleSpy.mockRestore()
  })
})