import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { ToastProvider } from '../contexts/ToastProvider'
import QueueBulkMapSeriesDialog from '../components/QueueBulkMapSeriesDialog'
import { useCreateThread, useUpdateThread, useReactivateThread } from '../hooks/useThread'
import { useQueueThreads, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
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
const mockedUseMoveToPosition = vi.mocked(useMoveToPosition)
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue)
const mockedUseCreateThread = vi.mocked(useCreateThread)
const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedUseReactivateThread = vi.mocked(useReactivateThread)
const mockedUseSession = vi.mocked(useSession)
const mockedBulkDialog = vi.mocked(QueueBulkMapSeriesDialog)

interface CapturedBulkProps {
  isOpen?: boolean
  isScopeLoading?: boolean
  isScopeIncomplete?: boolean
  scopeSeriesCount?: number
  threadIds?: number[]
  threadTitles?: string[]
  onClose?: () => void
  onBatchCaptured?: () => void
}

function lastBulkDialogProps(): CapturedBulkProps | undefined {
  const call = mockedBulkDialog.mock.calls.at(-1)
  const props = call?.[0]
  if (props === undefined || props === null) return undefined
  // SAFETY: the mock is called by QueuePage with a single props object; the test only reads isOpen/threadIds/threadTitles.
  return props as CapturedBulkProps
}

describe('QueuePage bulk mapping wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // SAFETY: the test provides only the fields QueuePage reads; the hook's full return type is irrelevant to this wiring test.
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

    // SAFETY: QueuePage only reads mutate and isPending from these hooks; the full return type is irrelevant.
    mockedUseCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    // SAFETY: QueuePage only reads mutate and isPending from these hooks; the full return type is irrelevant.
    mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    // SAFETY: QueuePage only reads mutate and isPending from these hooks; the full return type is irrelevant.
    mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    // SAFETY: QueuePage only reads mutate and isPending from these hooks; the full return type is irrelevant.
    mockedUseMoveToPosition.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    // SAFETY: QueuePage only reads mutate and isPending from these hooks; the full return type is irrelevant.
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
    // SAFETY: QueuePage only reads data.snoozed_threads, data.skipped_thread_ids, data.skipped_threads, and refetch; the full return type is irrelevant.
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
    // SAFETY: the test provides only the fields QueuePage reads; the hook's full return type is irrelevant to this wiring test.
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

  it('keeps the bulk action reachable while unread queue pages remain', () => {
    // Issue #3922: the reader must be able to start a run even when no loaded
    // row needs mapping, because an unread page can still hold unmapped series.
    // SAFETY: the test provides only the fields QueuePage reads.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'fully_mapped' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore: vi.fn(),
      activeCount: 164,
    } as never)

    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(screen.getByTestId('queue-bulk-map-desktop')).not.toBeDisabled()
  })

  it('reads the remaining queue pages before the batch is captured', async () => {
    const user = userEvent.setup()
    // SAFETY: the test provides only the fields QueuePage reads; the hook's full return type is irrelevant to this wiring test.
    const loadMore = vi.fn().mockResolvedValue(undefined)
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore,
      activeCount: 164,
    } as never)

    const { rerender } = render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))

    // The batch is not captured from the first page alone.
    expect(loadMore).toHaveBeenCalled()
    expect(lastBulkDialogProps()).toMatchObject({ isOpen: true, isScopeLoading: true })

    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
        { id: 2, title: 'Justice League America', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 4, comicvine_mapping: { status: 'needs_review' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: null,
      loadMore,
      activeCount: 164,
    } as never)
    rerender(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(lastBulkDialogProps()).toMatchObject({
      isScopeLoading: false,
      threadIds: [1, 2],
      threadTitles: ['Batman', 'Justice League America'],
    })
  })

  it('stops preparing and draining once the batch is captured', async () => {
    const user = userEvent.setup()
    const loadMore = vi.fn().mockResolvedValue(undefined)
    // Issue #3922 review: every saved mapping resets the Queue loader and drops
    // the loaded pages, so an open run must not restart the drain — the
    // preparing dialog would reopen beneath the mapping or results dialog and
    // the remaining pages would be re-fetched after every saved series.
    // SAFETY: the test provides only the fields QueuePage reads.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore,
      activeCount: 164,
    } as never)

    const { rerender } = render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))
    expect(loadMore).toHaveBeenCalledTimes(1)
    expect(lastBulkDialogProps()).toMatchObject({ isOpen: true, isScopeLoading: true })

    // The cursor finishes reading, so the batch is captured and the dialog
    // settles the run's scope with the host.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
        { id: 2, title: 'Superman', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 8, comicvine_mapping: { status: 'partial' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: null,
      loadMore,
      activeCount: 164,
    } as never)
    rerender(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )
    expect(lastBulkDialogProps()).toMatchObject({ isScopeLoading: false })
    act(() => {
      lastBulkDialogProps()?.onBatchCaptured?.()
    })

    // A saved mapping resets the Queue loader: pages drop and the cursor
    // returns. The settled run must leave the open dialog alone.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore,
      activeCount: 164,
    } as never)
    rerender(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(loadMore).toHaveBeenCalledTimes(1)
    expect(lastBulkDialogProps()).toMatchObject({ isScopeLoading: false })
  })

  it('drains again only when a fresh run opens after the settled one', async () => {
    const user = userEvent.setup()
    const loadMore = vi.fn().mockResolvedValue(undefined)
    // SAFETY: the test provides only the fields QueuePage reads.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
      ],
      isPending: false,
      isError: false,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore,
      activeCount: 164,
    } as never)

    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))
    expect(loadMore).toHaveBeenCalledTimes(1)
    act(() => {
      lastBulkDialogProps()?.onBatchCaptured?.()
    })

    // The previous run closes; reopening without a saved batch is a fresh run,
    // so the drain reads the cursor again before its capture.
    act(() => {
      lastBulkDialogProps()?.onClose?.()
    })
    expect(lastBulkDialogProps()).toMatchObject({ isOpen: false })

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))
    expect(loadMore).toHaveBeenCalledTimes(2)
    expect(lastBulkDialogProps()).toMatchObject({ isOpen: true, isScopeLoading: true })
  })

  it('reports a queue scope it could not finish loading', () => {
    // SAFETY: the test provides only the fields QueuePage reads.
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Batman', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 10, comicvine_mapping: { status: 'unresolved' } },
      ],
      isPending: false,
      isError: true,
      isLoadingMore: false,
      nextPageToken: 'page-2',
      loadMore: vi.fn().mockResolvedValue(undefined),
      activeCount: 164,
    } as never)

    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>,
    )

    // A failed page stops the drain instead of retrying forever, and the results
    // explain that the batch may be a subset of the queue.
    expect(lastBulkDialogProps()).toMatchObject({ isScopeIncomplete: true })
  })
})
