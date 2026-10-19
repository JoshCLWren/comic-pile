import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { cast } from '../utils/cast'
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

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.stubGlobal('alert', vi.fn())
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
  // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: mock return object satisfies the hook return type; as never bridges the type gap
  vi.mocked(useSession).mockReturnValue({
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

describe('Queue search with incomplete data', () => {
  it('shows loading state when searching and there are active threads but filtered results are empty (likely still loading)', async () => {
    const user = userEvent.setup()
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
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: 'next-page-token',
      loadMore: vi.fn().mockResolvedValue(undefined),
      activeCount: 10, // Total count is higher than what's loaded
    })

    renderQueue()

    // Trigger a search to enter the searching state
    const searchInput = screen.getByPlaceholderText('Search...')
    await user.type(searchInput, 'NonExistent')

    // Wait for the debounce delay to ensure the search state is properly entered
    await vi.waitFor(() => {
      // Since we're searching for something that doesn't exist and there are active threads,
      // it should show "Loading series..." instead of "No active series match your search"
      expect(screen.getByText('Loading series...')).toBeInTheDocument()
      expect(screen.queryByText('No active series match your search')).not.toBeInTheDocument()
    })
  })

  it('shows "No active series match your search" when searching and there are no active threads at all', async () => {
    const user = userEvent.setup()
    mockedUseQueueThreads.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
      activeCount: 0,
    })

    renderQueue()

    // Trigger a search to enter the searching state
    const searchInput = screen.getByPlaceholderText('Search...')
    await user.type(searchInput, 'Saga')

    // Wait for the debounce delay to ensure the search state is properly entered
    await vi.waitFor(() => {
      expect(screen.getByText('No active series match your search')).toBeInTheDocument()
      expect(screen.queryByText('Loading series...')).not.toBeInTheDocument()
    })
  })

  it('shows search results when search has matches', async () => {
    const user = userEvent.setup()
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
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
      activeCount: 2,
    })

    renderQueue()

    // Simulate a search that matches "Saga"
    const searchInput = screen.getByPlaceholderText('Search...')
    await user.type(searchInput, 'Saga')

    // Wait for the debounce delay to ensure the search state is properly entered
    await vi.waitFor(() => {
      // Should show the Saga result
      expect(screen.getByText('Saga')).toBeInTheDocument()
      expect(screen.queryByText('Loading series...')).not.toBeInTheDocument()
      expect(screen.queryByText('No active series match your search')).not.toBeInTheDocument()
      // Verify that Spawn is filtered out
      expect(screen.queryByText('Spawn')).not.toBeInTheDocument()
    })
  })
})