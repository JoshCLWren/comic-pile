import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useQueueThreads, useShuffleQueue } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../hooks/useThread'
import QueuePage from '../pages/QueuePage'

vi.mock('../hooks/useThread', () => ({
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useDeleteThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
  useQueueThreads: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn(), useUnsnooze: vi.fn() }))
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
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

// SAFETY: cast mocked hook to a callable fn type so tests can stub return values
const mockedUseQueueThreads = vi.mocked(useQueueThreads) as unknown as ReturnType<typeof vi.fn>

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

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.stubGlobal('alert', vi.fn())
  // SAFETY: mockReturnValue accepts partial hook returns; never cast bypasses full-type requirements
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useSession).mockReturnValue({
    data: { pending_thread_id: 1, snoozed_threads: [] },
    refetch: vi.fn(),
  } as never)
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as never)
})

describe('Queue search-key transition loading treatment', () => {
  it('keeps the list and controls rendered (no full-page loader) when a search commit is pending with previous data', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        {
          id: 1,
          title: 'Saga',
          format: 'Comic',
          status: 'active',
          queue_position: 1,
          issues_remaining: 5,
        },
        {
          id: 2,
          title: 'Spawn',
          format: 'Comic',
          status: 'active',
          queue_position: 2,
          issues_remaining: 5,
        },
      ],
      isPending: true,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })

    renderQueue()

    // The full-page loader (`.h-screen` container) must NOT replace the Queue
    // page: controls and the previously rendered rows survive the pending
    // search transition. An inline footer spinner is acceptable and not the
    // destructive full-screen path.
    expect(document.querySelector('.h-screen')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Series queue' })).toBeInTheDocument()
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText('Spawn')).toBeInTheDocument()
  })

  it('still renders the full-page loader only when there is no data at all', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [],
      isPending: true,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })

    renderQueue()

    expect(document.querySelector('.h-screen')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Series queue' })).not.toBeInTheDocument()
  })
})