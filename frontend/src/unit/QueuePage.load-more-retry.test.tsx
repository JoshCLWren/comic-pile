import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useQueueThreads,
  useShuffleQueue,
} from '../hooks/useQueue'
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

const mockedUseQueueThreads = vi.mocked(useQueueThreads) as unknown as ReturnType<typeof vi.fn>
const mockedUseSession = vi.mocked(useSession) as unknown as ReturnType<typeof vi.fn>
const mockedUseSnooze = vi.mocked(useSnooze) as unknown as ReturnType<typeof vi.fn>
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as unknown as ReturnType<typeof vi.fn>

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

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.stubGlobal('alert', vi.fn())
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as never)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderQueue(): void {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>,
  )
}

it('offers a retry affordance when the next-page fetch fails', async () => {
  const loadMore = vi.fn().mockResolvedValue(undefined)
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
    ],
    isPending: false,
    isError: true,
    refetch: vi.fn(),
    nextPageToken: 'page-2',
    loadMore,
  })
  mockedUseSession.mockReturnValue({
    data: { pending_thread_id: 1, snoozed_threads: [] },
    refetch: vi.fn(),
  })

  const user = userEvent.setup()
  renderQueue()

  const retry = await screen.findByTestId('queue-load-more-retry')
  expect(retry).toBeInTheDocument()

  await user.click(retry)

  await waitFor(() => {
    expect(loadMore).toHaveBeenCalled()
  })
})

it('does not offer a retry affordance when there is no further page', async () => {
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
    ],
    isPending: false,
    isError: true,
    refetch: vi.fn(),
    nextPageToken: null,
    loadMore: vi.fn().mockResolvedValue(undefined),
  })
  mockedUseSession.mockReturnValue({
    data: { pending_thread_id: 1, snoozed_threads: [] },
    refetch: vi.fn(),
  })

  renderQueue()

  expect(screen.queryByTestId('queue-load-more-retry')).not.toBeInTheDocument()
})
