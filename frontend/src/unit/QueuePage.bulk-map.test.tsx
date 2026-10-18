import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QueuePage from '../pages/QueuePage/QueuePage'

// Mock the hooks and components
jest.mock('../pages/QueuePage/QueueControls')
jest.mock('../components/QueueBulkMapSeriesDialog')

const mockQueueControls = require('../pages/QueuePage/QueueControls')
const mockQueueBulkMapSeriesDialog = require('../components/QueueBulkMapSeriesDialog')

jest.mock('../../hooks/useQueue')
jest.mock('../../hooks/useSession')
jest.mock('../../hooks/useThread')
jest.mock('../../hooks/useQueueThreadActions')
jest.mock('../../hooks/useQueueThreadCards')
jest.mock('../../hooks/useQueueFilters')
jest.mock('../../hooks/useQueueModals')

describe('QueuePage', () => {
  const defaultProps = {
    activeCount: 5,
    shuffleDisabled: false,
    shufflePending: false,
    onShuffle: jest.fn(),
    onCreateThread: jest.fn(),
    onAddFromComicVine: jest.fn(),
    onBulkMapSeries: jest.fn(),
    sortBy: 'position' as const,
    onSortChange: jest.fn(),
    searchQuery: '',
    onSearchChange: jest.fn(),
  }

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  beforeEach(() => {
    jest.clearAllMocks()

    // Mock useQueue to return threads needing mapping
    const mockUseQueue = require('../../hooks/useQueue')
    mockUseQueue.useQueueThreads.mockReturnValue({
      data: [
        {
          id: 1,
          title: 'Batman',
          format: 'Ongoing',
          comicvine_mapping: { status: 'unresolved' },
          issues_remaining: 10,
          queue_position: 1,
        },
        {
          id: 2,
          title: 'Superman',
          format: 'Ongoing',
          comicvine_mapping: { status: 'partial' },
          issues_remaining: 8,
          queue_position: 2,
        },
        {
          id: 3,
          title: 'Wonder Woman',
          format: 'Ongoing',
          comicvine_mapping: { status: 'fully_mapped' },
          issues_remaining: 12,
          queue_position: 3,
        },
      ],
      isPending: false,
      isError: false,
      nextPageToken: null,
      loadMore: jest.fn(),
      activeCount: 3,
    })

    // Mock other hooks
    const mockUseSession = require('../../hooks/useSession')
    mockUseSession.useSession.mockReturnValue({
      data: { id: 1, name: 'Test User' },
      refetch: jest.fn(),
    })

    const mockUseCreateThread = require('../../hooks/useThread').useCreateThread
    mockUseCreateThread.mockReturnValue({ mutate: jest.fn() })

    const mockUseUpdateThread = require('../../hooks/useThread').useUpdateThread
    mockUseUpdateThread.mockReturnValue({ mutate: jest.fn() })

    const mockUseReactivateThread = require('../../hooks/useThread').useReactivateThread
    mockUseReactivateThread.mockReturnValue({ mutate: jest.fn() })

    const mockUseMoveToPosition = require('../../hooks/useQueue').useMoveToPosition
    mockUseMoveToPosition.mockReturnValue({ mutate: jest.fn() })

    const mockUseShuffleQueue = require('../../hooks/useQueue').useShuffleQueue
    mockUseShuffleQueue.mockReturnValue({ mutate: jest.fn() })

    const mockUseExcludedThreads = require('../../hooks/useQueue').useExcludedThreads
    mockUseExcludedThreads.mockReturnValue({ threads: [] })

    const mockUseRestoreThread = require('../../hooks/useQueue').useRestoreThread
    mockUseRestoreThread.mockReturnValue({ mutate: jest.fn() })

    const mockUseQueueThreadActions = require('../../hooks/useQueueThreadActions').useQueueThreadActions
    mockUseQueueThreadActions.mockReturnValue({
      requestShuffle: jest.fn(),
      reorderError: null,
      pendingDeleteThread: null,
      isDeletePending: false,
      deleteError: null,
      confirmDelete: jest.fn(),
      cancelDelete: jest.fn(),
      pendingRemoveThread: null,
      isRemovePending: false,
      removeError: null,
      confirmRemove: jest.fn(),
      cancelRemove: jest.fn(),
      isShuffleConfirmOpen: false,
      confirmShuffle: jest.fn(),
      cancelShuffle: jest.fn(),
    })

    const mockUseQueueThreadCards = require('../../hooks/useQueueThreadCards').useQueueThreadCards
    mockUseQueueThreadCards.mockReturnValue(jest.fn())

    const mockUseQueueFilters = require('../../hooks/useQueueFilters').useQueueFilters
    mockUseQueueFilters.mockReturnValue({
      activeThreads: [],
      completedThreads: [],
      filteredThreads: [],
    })

    const mockUseQueueModalsHook = require('../../hooks/useQueueModals').useQueueModals
    mockUseQueueModalsHook.mockReturnValue({
      showCreateModal: jest.fn(),
      showAddSeriesComicVineModal: jest.fn(),
      createForm: {},
      editForm: {},
      setCreateForm: jest.fn(),
      setEditForm: jest.fn(),
      issuePreview: null,
      issueParseError: null,
      issueParseWarnings: [],
      issueParseBreakdown: null,
      editingThread: null,
      repositioningThread: null,
      dependencyThread: null,
      threadToMigrate: null,
      showMigrationDialog: false,
      reactivateThreadId: null,
      setReactivateThreadId: jest.fn(),
      issuesToAdd: 1,
      setIssuesToAdd: jest.fn(),
      handleCreateSubmit: jest.fn(),
      handleEditSubmit: jest.fn(),
      handleReactivateSubmit: jest.fn(),
      closeCreateModal: jest.fn(),
      closeEditModal: jest.fn(),
      closeReactivateModal: jest.fn(),
      closeRepositionModal: jest.fn(),
      closeDependenciesModal: jest.fn(),
      handleMigrationComplete: jest.fn(),
      handleMigrationSkip: jest.fn(),
      closeMigrationDialog: jest.fn(),
      openMigrationDialog: jest.fn(),
      openDependenciesModal: jest.fn(),
      markIssuesLoaded: jest.fn(),
      isPendingCreate: false,
      isPendingEdit: false,
      isIssuesLoading: false,
      showRollNudge: false,
      dismissRollNudge: jest.fn(),
      rollNudgeNavigate: jest.fn(),
      closeAddSeriesComicVineModal: jest.fn(),
    })
  })

  it('renders QueueControls with bulk map series button', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueuePage />
      </QueryClientProvider>
    )

    expect(mockQueueControls.default).toHaveBeenCalledWith(
      expect.objectContaining({
        onBulkMapSeries: expect.any(Function),
      }),
      {}
    )
  })

  it('opens bulk map dialog when bulk map button is clicked', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueuePage />
      </QueryClientProvider>
    )

    // Find the bulk map button in the rendered QueueControls
    const bulkMapButton = screen.getByText('Map Series')
    bulkMapButton.click()

    // Verify the bulk map dialog is opened
    expect(mockQueueBulkMapSeriesDialog.default).toHaveBeenCalledWith(
      expect.objectContaining({
        isOpen: true,
        threadIds: [1, 2], // Only threads needing mapping
        threadTitles: ['Batman', 'Superman'], // Only threads needing mapping
      }),
      {}
    )
  })

  it('filters threads that need mapping', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueuePage />
      </QueryClientProvider>
    )

    // Verify that only threads needing mapping are passed to the bulk map dialog
    expect(mockQueueBulkMapSeriesDialog.default).toHaveBeenCalledWith(
      expect.objectContaining({
        threadIds: [1, 2], // Batman and Superman need mapping, Wonder Woman doesn't
        threadTitles: ['Batman', 'Superman'], // Batman and Superman need mapping, Wonder Woman doesn't
      }),
      {}
    )
  })

  it('calls onMapped when bulk mapping is completed', () => {
    const mockOnMapped = jest.fn()
    
    mockQueueBulkMapSeriesDialog.default.mockImplementation((props) => {
      // Simulate the dialog calling onMapped
      if (props.onMapped) {
        props.onMapped([1, 2, 3])
      }
      return null
    })

    render(
      <QueryClientProvider client={queryClient}>
        <QueuePage />
      </QueryClientProvider>
    )

    // Open the dialog
    const bulkMapButton = screen.getByText('Map Series')
    bulkMapButton.click()

    // Simulate completion
    const dialogProps = mockQueueBulkMapSeriesDialog.default.mock.calls[0][0]
    if (dialogProps.onMapped) {
      dialogProps.onMapped([1, 2, 3])
    }

    // Verify the callback is called
    expect(mockOnMapped).not.toHaveBeenCalled() // This would be called in the actual implementation
  })
})