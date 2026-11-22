import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cast } from '../utils/cast'
import { ToastProvider } from '../contexts/ToastProvider'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useQueueThreads, useShuffleQueue } from '../hooks/useQueue'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useSnooze } from '../hooks/useSnooze'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../hooks/useThread'
import QueuePage from '../pages/QueuePage'

vi.mock('../hooks/useCompletedThreads', () => ({
  useCompletedThreads: vi.fn(() => ({
    threads: [], hasNextPage: false, isLoadingMore: false, isError: false,
    loadMore: vi.fn(), retry: vi.fn(),
  })),
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
  useRestoreExclusionGroup: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
  useQueueThreads: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn() }))
vi.mock('../hooks/useQueueBlockingInfo', () => ({ useQueueBlockingInfo: vi.fn(() => ({})) }))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: vi.fn() }))

vi.mock('../services/api', () => ({
  threadsApi: { setPending: vi.fn() },
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

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

const mockedUseQueueThreads = cast<ReturnType<typeof vi.fn>>(vi.mocked(useQueueThreads))

class NoopIntersectionObserver {
  observe(): void {
    /* no-op */
  }
  unobserve(): void {
    /* no-op */
  }
  disconnect(): void {
    /* no-op */
  }
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

function renderQueue(): void {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>,
  )
}

const queueThread = (id: number, title: string, position: number) => ({
  id,
  title,
  format: 'Comic',
  status: 'active',
  queue_position: position,
  issues_remaining: 5,
})

function mockQueue(overrides: Record<string, unknown> = {}): void {
  mockedUseQueueThreads.mockReturnValue({
    data: [queueThread(1, 'Saga', 1), queueThread(2, 'Spawn', 2)],
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: null,
    loadMore: vi.fn().mockResolvedValue(undefined),
    activeCount: 5,
    filteredCount: 5,
    isPlaceholderData: false,
    isFetchNextPageError: false,
    ...overrides,
  } as never)
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  // SAFETY: mockReturnValue accepts partial hook returns; never cast bypasses full-type requirements
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mock return object satisfies the hook return type; as never bridges the type gap
  vi.mocked(useRollBootstrap).mockReturnValue({
    data: { pending_thread_id: 1, snoozed_threads: [] },
    refetch: vi.fn(),
  } as never)
  // SAFETY: mock return object satisfies the hook return type; as never bridges the type gap
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as never)
})

describe('Queue search result count (#3614)', () => {
  it('shows M of M on the initial unfiltered view', () => {
    mockQueue({ activeCount: 5, filteredCount: 5 })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('5 of 5 series')
  })

  it('shows N of M for a filtered search that matches part of the collection', () => {
    mockQueue({ activeCount: 5, filteredCount: 2 })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('2 of 5 series')
  })

  it('shows 0 of M when no series match the applied search', () => {
    mockQueue({ activeCount: 5, filteredCount: 0, data: [] })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('0 of 5 series')
  })

  it('keeps the settled counts across cursor pages instead of visible-page counts', () => {
    mockQueue({
      data: [queueThread(1, 'Saga', 1)],
      nextPageToken: 'tok-2',
      activeCount: 5,
      filteredCount: 5,
    })
    renderQueue()

    // One bounded page (1 row) is visible, but the count must restate the
    // whole-collection totals, never the rendered-page size.
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('5 of 5 series')
  })

  it('does not restate the previous query count while a search transition is pending', () => {
    // Placeholder rows from the previous key ("Saga"/"Spawn") are on screen
    // while the new key's first page fetches; its count (2 of 5) has not
    // arrived yet.
    mockQueue({ isPlaceholderData: true, filteredCount: 2 })
    renderQueue()

    const count = screen.getByTestId('queue-result-count')
    expect(count).toHaveTextContent('Updating series count…')
    expect(count).not.toHaveTextContent('2 of 5 series')
  })

  it('does not invent a count when the settled response omits filtered_count', () => {
    mockQueue({ filteredCount: undefined })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Updating series count…')
  })

  it('shows an unavailable count when the first page fails instead of success copy', () => {
    mockQueue({ data: undefined, isError: true, isFetchNextPageError: false, filteredCount: undefined })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Series count unavailable.')
  })

  it('keeps the settled counts when only a next-page fetch fails', () => {
    mockQueue({ isError: true, isFetchNextPageError: true, activeCount: 5, filteredCount: 5 })
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('5 of 5 series')
  })

  it('exposes the count as a polite live status for assistive tech', () => {
    mockQueue({ activeCount: 5, filteredCount: 2 })
    renderQueue()

    const count = screen.getByTestId('queue-result-count')
    expect(count).toHaveAttribute('role', 'status')
    expect(count).toHaveAttribute('aria-live', 'polite')
  })
})
