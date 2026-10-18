import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { ToastProvider } from '../contexts/ToastProvider'
import QueueBulkMapSeriesDialog from '../components/QueueBulkMapSeriesDialog'
import { useCreateThread, useUpdateThread, useReactivateThread } from '../hooks/useThread'
import { useQueueThreads } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'

vi.mock('../components/QueueBulkMapSeriesDialog', () => ({
  default: vi.fn(() => null),
}))

vi.mock('../hooks/useThread', () => ({
  useExcludeThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useDeleteThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useExcludedThreads: vi.fn(() => ({ threads: [], isPending: false, isError: false })),
  useRestoreThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
  useQueueThreads: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn(), useUnsnooze: vi.fn() }))
vi.mock('../hooks/useQueueBlockingInfo', () => ({ useQueueBlockingInfo: vi.fn(() => ({})) }))

vi.mock('../services/api-threads', () => ({
  threadsApi: { setPending: vi.fn().mockResolvedValue({}) },
}))

vi.mock('../services/api-dependencies', () => ({
  dependenciesApi: {
    listBlockedThreadIds: vi.fn().mockResolvedValue([]),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    create: vi.fn().mockResolvedValue({ issues: [] }),
    markRead: vi.fn().mockResolvedValue(undefined),
    bulkMarkRead: vi.fn().mockResolvedValue(undefined),
    bulkMarkUnread: vi.fn().mockResolvedValue(undefined),
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: vi.fn(() => ({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  })),
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

vi.mock('../pages/QueuePage/QueueModals', () => ({ QueueModals: () => null }))

vi.mock('../pages/QueuePage/useQueueFilters', () => ({
  useQueueFilters: vi.fn(() => ({
    activeThreads: [],
    completedThreads: [],
    filteredThreads: [],
  })),
}))

vi.mock('../pages/QueuePage/useQueueThreadCards', () => ({
  useQueueThreadCards: vi.fn(() => () => null),
}))

vi.mock('../pages/QueuePage/useQueueThreadActions', () => ({
  useQueueThreadActions: vi.fn(() => ({
    requestShuffle: vi.fn(),
    reorderError: null,
    pendingDeleteThread: null,
    isDeletePending: false,
    deleteError: null,
    confirmDelete: vi.fn(),
    cancelDelete: vi.fn(),
    pendingRemoveThread: null,
    isRemovePending: false,
    removeError: null,
    confirmRemove: vi.fn(),
    cancelRemove: vi.fn(),
    isShuffleConfirmOpen: false,
    confirmShuffle: vi.fn(),
    cancelShuffle: vi.fn(),
  })),
}))

const mockedUseQueueThreads = vi.mocked(useQueueThreads)
const mockedUseCreateThread = vi.mocked(useCreateThread)
const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedUseReactivateThread = vi.mocked(useReactivateThread)
const mockedUseSession = vi.mocked(useSession)
const mockedBulkDialog = vi.mocked(QueueBulkMapSeriesDialog)

interface CapturedBulkProps {
  isOpen?: boolean
  threadIds?: number[]
  threadTitles?: string[]
}

function lastBulkDialogProps(): CapturedBulkProps | undefined {
  const call = mockedBulkDialog.mock.calls.at(-1)
  return call?.[0] as unknown as CapturedBulkProps | undefined
}

describe('QueuePage bulk mapping wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
        { id: 2, title: 'Superman', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 8, comicvine_mapping: { status: 'partial' } },
        { id: 3, title: 'Wonder Woman', format: 'Comic', status: 'active', queue_position: 3, issues_remaining: 12, comicvine_mapping: { status: 'fully_mapped' } },
      ],
      isPending: false,
      isError: false,
      nextPageToken: null,
      loadMore: vi.fn(),
      activeCount: 3,
    } as never)

    mockedUseCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    mockedUseSession.mockReturnValue({
      data: { snoozed_threads: [], skipped_thread_ids: [], skipped_threads: [] },
      refetch: vi.fn(),
    } as never)
  })

  it('offers only series that still need mapping to the bulk dialog', () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(lastBulkDialogProps()).toMatchObject({
      isOpen: false,
      threadIds: [1, 2],
      threadTitles: ['Batman', 'Superman'],
    })
  })

  it('opens the bulk dialog from the queue controls', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))

    expect(lastBulkDialogProps()).toMatchObject({ isOpen: true })
  })

  it('disables the bulk action when every series is mapped', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'fully_mapped' } },
      ],
      isPending: false,
      isError: false,
      nextPageToken: null,
      loadMore: vi.fn(),
      activeCount: 1,
    } as never)

    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(screen.getByTestId('queue-bulk-map-desktop')).toBeDisabled()
    expect(lastBulkDialogProps()).toMatchObject({ threadIds: [] })
  })
})
