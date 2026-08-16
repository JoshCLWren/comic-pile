import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { useCreateThread, useReactivateThread, useUpdateThread } from '../hooks/useThread'
import { useMoveToPosition, useQueueThreads, useShuffleQueue } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'

vi.mock('../hooks/useThread', () => ({
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useMoveToPosition: vi.fn(),
  useQueueThreads: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({
  useSession: vi.fn(),
}))

vi.mock('../pages/QueuePage/useQueueFilters', () => ({
  useQueueFilters: vi.fn((threads: Array<{ id: number; title: string }> | null) => ({
    activeThreads: threads ?? [],
    completedThreads: [],
    filteredThreads: threads ?? [],
  })),
}))

vi.mock('../pages/QueuePage/useQueueThreadActions', () => ({
  useQueueThreadActions: vi.fn(() => ({
    reorderError: null,
    handleShuffle: vi.fn(),
  })),
}))

vi.mock('../pages/QueuePage/useQueueModals', () => ({
  useQueueModals: vi.fn(() => ({
    isAnyModalOpen: false,
    repositioningThread: null,
    showCreateModal: vi.fn(),
    openReactivateModal: vi.fn(),
  })),
}))

vi.mock('../pages/QueuePage/QueueControls', () => ({
  QueueControls: () => null,
}))

vi.mock('../pages/QueuePage/QueueList', () => ({
  QueueList: ({ filteredThreads }: { filteredThreads: Array<{ id: number; title: string }> }) => (
    <div data-testid="queue-list">
      {filteredThreads.map((thread) => <div key={thread.id}>{thread.title}</div>)}
    </div>
  ),
}))

vi.mock('../pages/QueuePage/CompletedThreadsSection', () => ({
  default: () => null,
}))

vi.mock('../pages/QueuePage/QueueModals', () => ({
  QueueModals: () => null,
}))

const mockedUseQueueThreads = vi.mocked(useQueueThreads) as any
const mockedUseCreateThread = vi.mocked(useCreateThread) as any
const mockedUseUpdateThread = vi.mocked(useUpdateThread) as any
const mockedUseReactivateThread = vi.mocked(useReactivateThread) as any
const mockedUseMoveToPosition = vi.mocked(useMoveToPosition) as any
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue) as any
const mockedUseSession = vi.mocked(useSession) as any

const thread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  status: 'active',
  queue_position: 1,
  issues_remaining: 5,
}

function renderQueue() {
  return render(
    <BrowserRouter>
      <QueuePage />
    </BrowserRouter>,
  )
}

beforeEach(() => {
  mockedUseCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToPosition.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSession.mockReturnValue({ data: { snoozed_threads: [] }, refetch: vi.fn() })
})

it('shows the initial full-screen loader before any queue data exists', () => {
  mockedUseQueueThreads.mockReturnValue({
    data: null,
    isPending: true,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: null,
    loadMore: vi.fn(),
  })

  renderQueue()

  expect(screen.queryByTestId('queue-list')).not.toBeInTheDocument()
})

it('keeps loaded rows visible and shows the incremental-loading state while another page is loading', () => {
  mockedUseQueueThreads.mockReturnValue({
    data: [thread],
    isPending: true,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: 'next-page',
    loadMore: vi.fn(),
  })

  renderQueue()

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByTestId('queue-loading-more')).toBeInTheDocument()
  expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()
})

it('loads the next page when the infinite-scroll sentinel becomes visible and absorbs request rejection', async () => {
  const loadMore = vi.fn().mockRejectedValue(new Error('next page unavailable'))
  let observerCallback: IntersectionObserverCallback | null = null
  class CapturingIntersectionObserver {
    constructor(callback: IntersectionObserverCallback) {
      observerCallback = callback
    }

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

  mockedUseQueueThreads.mockReturnValue({
    data: [thread],
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: 'next-page',
    loadMore,
  })

  vi.stubGlobal('IntersectionObserver', CapturingIntersectionObserver)
  try {
    renderQueue()

    expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()
    act(() => {
      observerCallback?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    await waitFor(() => expect(loadMore).toHaveBeenCalledTimes(1))
  } finally {
    vi.unstubAllGlobals()
  }
})

it('shows an incremental-load error with a retry control without discarding the loaded queue', () => {
  mockedUseQueueThreads.mockReturnValue({
    data: [thread],
    isPending: false,
    isError: true,
    refetch: vi.fn(),
    nextPageToken: 'next-page',
    loadMore: vi.fn(),
  })

  renderQueue()

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load the next batch of threads.")
  expect(screen.getByTestId('queue-load-more-retry')).toBeInTheDocument()
})

it('does not show an incremental error before the queue has produced a data snapshot', () => {
  mockedUseQueueThreads.mockReturnValue({
    data: null,
    isPending: false,
    isError: true,
    refetch: vi.fn(),
    nextPageToken: 'next-page',
    loadMore: vi.fn(),
  })

  renderQueue()

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()
})
