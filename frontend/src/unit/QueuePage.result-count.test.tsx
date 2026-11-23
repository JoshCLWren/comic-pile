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

function mockQueue(resultCountText: string, overrides: Record<string, unknown> = {}): void {
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
    resultCountText,
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

describe('Queue search result count display (#3614)', () => {
  it('renders the settled N of M count next to the search controls', () => {
    mockQueue('2 of 5 series')
    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('2 of 5 series')
  })

  it('renders the updating and unavailable states from the loader', () => {
    mockQueue('Updating series count…')
    renderQueue()
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Updating series count…')
  })

  it('exposes the count as a polite live status for assistive tech', () => {
    mockQueue('5 of 5 series')
    renderQueue()

    const count = screen.getByTestId('queue-result-count')
    expect(count).toHaveAttribute('role', 'status')
    expect(count).toHaveAttribute('aria-live', 'polite')
  })
})
