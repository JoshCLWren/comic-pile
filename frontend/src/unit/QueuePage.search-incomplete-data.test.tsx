import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
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
import { useQueueListLoading } from '../pages/QueuePage/useQueueListLoading'

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
vi.mock('../pages/QueuePage/useQueueListLoading', () => ({ useQueueListLoading: vi.fn() }))
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

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.mocked(useQueueListLoading).mockReturnValue(false)
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

describe('Queue search with incomplete data', () => {
  it('shows loading instead of previous-key rows while a non-empty Queue search is pending', async () => {
    const user = userEvent.setup()
    vi.mocked(useQueueListLoading).mockReturnValue(true)
    const previousRows = [
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
    ]
    mockedUseQueueThreads.mockImplementation((search?: string) => {
      const searchPending = Boolean(search?.trim())
      return {
        data: previousRows,
        isPending: false,
        isError: false,
        refetch: vi.fn(),
        nextPageToken: 'next-page-token',
        loadMore: vi.fn().mockResolvedValue(undefined),
        activeCount: 10,
        filteredCount: searchPending ? null : 10,
        isPlaceholderData: searchPending,
        resultCountText: searchPending ? 'Updating series count…' : '10 of 10 series',
      }
    })

    renderQueue()

    const searchInput = screen.getByPlaceholderText('Search...')
    await user.type(searchInput, 'NonExistent')

    await vi.waitFor(() => {
      expect(mockedUseQueueThreads).toHaveBeenCalledWith('NonExistent', 'position')
      expect(screen.getByText('Loading series...')).toBeInTheDocument()
      expect(screen.queryByText('No active series match your search')).not.toBeInTheDocument()
      expect(screen.queryByText('Saga')).not.toBeInTheDocument()
      expect(screen.queryByText('Spawn')).not.toBeInTheDocument()
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

  it('renders only the server rows returned for the applied search', async () => {
    const user = userEvent.setup()
    const serverRows = [
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
    ]
    mockedUseQueueThreads.mockImplementation((search?: string) => {
      const term = search?.trim().toLowerCase() ?? ''
      const rows = serverRows.filter((thread) => thread.title.toLowerCase().includes(term))
      return {
        data: rows,
        isPending: false,
        isError: false,
        refetch: vi.fn(),
        nextPageToken: null,
        loadMore: vi.fn().mockResolvedValue(undefined),
        activeCount: 2,
        filteredCount: rows.length,
        isPlaceholderData: false,
        resultCountText: `${rows.length} of 2 series`,
      }
    })

    renderQueue()

    const searchInput = screen.getByPlaceholderText('Search...')
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('2 of 2 series')
    await user.type(searchInput, 'Saga')

    await vi.waitFor(() => {
      expect(mockedUseQueueThreads).toHaveBeenCalledWith('Saga', 'position')
      expect(screen.getByText('Saga')).toBeInTheDocument()
      expect(screen.queryByText('Loading series...')).not.toBeInTheDocument()
      expect(screen.queryByText('No active series match your search')).not.toBeInTheDocument()
      expect(screen.queryByText('Spawn')).not.toBeInTheDocument()
      expect(screen.getByTestId('queue-result-count')).toHaveTextContent('1 of 2 series')
    })

    await user.click(screen.getByRole('button', { name: 'Clear search' }))
    await vi.waitFor(() => {
      expect(screen.getByTestId('queue-result-count')).toHaveTextContent('2 of 2 series')
      expect(screen.getByText('Saga')).toBeInTheDocument()
      expect(screen.getByText('Spawn')).toBeInTheDocument()
    })

    await user.type(searchInput, 'zzz')
    await vi.waitFor(() => {
      expect(mockedUseQueueThreads).toHaveBeenLastCalledWith('zzz', 'position')
      expect(screen.getByTestId('queue-result-count')).toHaveTextContent('0 of 2 series')
      expect(screen.getByText('No active series match your search')).toBeInTheDocument()
    })
  })

  it('shows a load error instead of an empty queue when the initial request fails', async () => {
    const user = userEvent.setup()
    const refetch = vi.fn().mockResolvedValue(undefined)
    mockedUseQueueThreads.mockReturnValue({
      data: null,
      isPending: false,
      isError: true,
      refetch,
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
      activeCount: null,
      filteredCount: null,
      isPlaceholderData: false,
      resultCountText: 'Series count unavailable.',
    })

    renderQueue()

    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Series count unavailable.')
    expect(screen.getByRole('alert')).toHaveTextContent('Couldn\'t load your queue.')
    expect(screen.queryByText('Nothing to roll yet')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('shows a search error instead of a zero-match state when the applied request fails', async () => {
    const user = userEvent.setup()
    const refetch = vi.fn().mockResolvedValue(undefined)
    const rows = [
      {
        id: 1,
        title: 'Saga',
        format: 'Comic',
        status: 'active',
        queue_position: 1,
        issues_remaining: 5,
      },
    ]
    mockedUseQueueThreads.mockImplementation((search?: string) =>
      search?.trim()
        ? {
            data: null,
            isPending: false,
            isError: true,
            refetch,
            nextPageToken: null,
            loadMore: vi.fn().mockResolvedValue(undefined),
            activeCount: null,
            filteredCount: null,
            isPlaceholderData: false,
            resultCountText: 'Series count unavailable.',
          }
        : {
            data: rows,
            isPending: false,
            isError: false,
            refetch,
            nextPageToken: null,
            loadMore: vi.fn().mockResolvedValue(undefined),
            activeCount: 1,
            filteredCount: 1,
            isPlaceholderData: false,
            resultCountText: '1 of 1 series',
          },
    )

    renderQueue()
    expect(screen.getByTestId('queue-result-count')).toHaveTextContent('1 of 1 series')

    await user.type(screen.getByPlaceholderText('Search...'), 'Saga')

    await vi.waitFor(() => {
      expect(mockedUseQueueThreads).toHaveBeenCalledWith('Saga', 'position')
      expect(screen.getByTestId('queue-result-count')).toHaveTextContent('Series count unavailable.')
      expect(screen.getByRole('alert')).toHaveTextContent('Couldn\'t load series matching your search.')
      expect(screen.queryByText('No active series match your search')).not.toBeInTheDocument()
      expect(screen.queryByText('Saga')).not.toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })
})
