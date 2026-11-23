import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cast } from '../utils/cast'
import { ToastProvider } from '../contexts/ToastProvider'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useQueueThreads, useShuffleQueue } from '../hooks/useQueue'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useSnooze } from '../hooks/useSnooze'
import { useCreateThread, useDeleteThread, useReactivateThread, useUpdateThread } from '../hooks/useThread'
import QueuePage from '../pages/QueuePage'

vi.mock('../hooks/useCompletedThreads', () => ({
  useCompletedThreads: vi.fn(() => ({ threads: [], hasNextPage: false, isLoadingMore: false, isError: false, loadMore: vi.fn(), retry: vi.fn() })),
}))
vi.mock('../hooks/useThread', () => ({
  useExcludeThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useCreateThread: vi.fn(), useUpdateThread: vi.fn(), useDeleteThread: vi.fn(), useReactivateThread: vi.fn(),
}))
vi.mock('../hooks/useQueue', () => ({
  useExcludedThreads: vi.fn(() => ({ threads: [], isPending: false, isError: false })),
  useRestoreThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useRestoreExclusionGroup: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useMoveToFront: vi.fn(), useMoveToBack: vi.fn(), useMoveToPosition: vi.fn(), useQueueThreads: vi.fn(), useShuffleQueue: vi.fn(),
}))
vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn() }))
vi.mock('../hooks/useQueueBlockingInfo', () => ({ useQueueBlockingInfo: vi.fn(() => ({})) }))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: vi.fn() }))
vi.mock('../services/api', () => ({
  threadsApi: { setPending: vi.fn() },
  dependenciesApi: { listBlockedThreadIds: vi.fn().mockResolvedValue([]), getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }) },
}))
vi.mock('../services/api-issues', () => ({
  issuesApi: { create: vi.fn().mockResolvedValue({ issues: [] }), markRead: vi.fn().mockResolvedValue(undefined), bulkMarkRead: vi.fn().mockResolvedValue(undefined), bulkMarkUnread: vi.fn().mockResolvedValue(undefined), migrateThread: vi.fn().mockResolvedValue({}) },
}))
vi.mock('../contexts/useToast', () => ({ useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })) }))

const mockedUseQueueThreads = cast<ReturnType<typeof vi.fn>>(vi.mocked(useQueueThreads))

class NoopIntersectionObserver { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }

function renderQueue() {
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
}

const baseThread = (id: number, title: string, pos = id) => ({ id, title, format: 'Comic', status: 'active', queue_position: pos, issues_remaining: 5 })

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useRollBootstrap).mockReturnValue({ data: { pending_thread_id: 1, snoozed_threads: [] }, refetch: vi.fn() } as never)
  vi.mocked(useBugReportRestore).mockReturnValue({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn(), restoreLastView: vi.fn() } as never)
})

describe('Queue result count display', () => {
  it('shows M of M series for an unfiltered applied view', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [baseThread(1, 'Alpha'), baseThread(2, 'Beta')],
      isPending: false, isError: false, isPlaceholderData: false, isFetching: false,
      refetch: vi.fn(), nextPageToken: null, loadMore: vi.fn(),
      activeCount: 2, filteredCount: 2,
    })
    renderQueue()
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('2 of 2 series')
  })

  it('shows 0 of M series when the applied search has no matches', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    mockedUseQueueThreads.mockReturnValue({
      data: [],
      isPending: false, isError: false, isPlaceholderData: false, isFetching: false,
      refetch: vi.fn(), nextPageToken: null, loadMore: vi.fn(),
      activeCount: 5, filteredCount: 0,
    })
    renderQueue()
    await user.type(screen.getByPlaceholderText('Search...'), 'nomatch')
    await new Promise((r) => setTimeout(r, 450))
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('0 of 5 series')
  })

  it('does not show a stale count during a placeholder search transition', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [baseThread(1, 'Alpha')],
      isPending: false, isError: false, isPlaceholderData: true, isFetching: true,
      refetch: vi.fn(), nextPageToken: null, loadMore: vi.fn(),
      activeCount: 5, filteredCount: 1, // old query count - must not be shown
    })
    renderQueue()
    const count = screen.getByTestId('queue-result-count')
    expect(count).toHaveTextContent('Updating series count…')
    expect(count).not.toHaveTextContent('1 of 5')
  })

  it('shows N of M series for a filtered applied search', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    mockedUseQueueThreads.mockReturnValue({
      data: [baseThread(1, 'Alpha')],
      isPending: false, isError: false, isPlaceholderData: false, isFetching: false,
      refetch: vi.fn(), nextPageToken: null, loadMore: vi.fn(),
      activeCount: 5, filteredCount: 1,
    })
    renderQueue()
    await user.type(screen.getByPlaceholderText('Search...'), 'Al')
    await new Promise((r) => setTimeout(r, 450))
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('1 of 5 series')
  })

  it('shows an unavailable count on error instead of fabricating success', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [baseThread(1, 'Alpha')],
      isPending: false, isError: true, isPlaceholderData: false, isFetching: false,
      refetch: vi.fn(), nextPageToken: null, loadMore: vi.fn(),
      activeCount: 5, filteredCount: 1,
    })
    renderQueue()
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Series count unavailable.')
  })
})
