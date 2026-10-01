import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
import { dependencyGroupsApi } from '../services/api-dependency-groups'
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

function activeThread(id: number, title: string) {
  return {
    id,
    title,
    format: 'Comic',
    status: 'active',
    queue_position: id,
    issues_remaining: 5,
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

let listForThreads: ReturnType<typeof vi.spyOn>

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

  listForThreads = vi
    .spyOn(dependencyGroupsApi, 'listForThreads')
    .mockResolvedValue({})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('QueuePage crossover batch loading', () => {
  it('requests crossover memberships once for the whole active queue instead of once per card', async () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        activeThread(1, 'Saga'),
        activeThread(2, 'Spawn'),
        activeThread(3, 'Invincible'),
        activeThread(4, 'Watchmen'),
        activeThread(5, 'Saga II'),
      ],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })

    renderQueue()

    await waitFor(() => {
      expect(listForThreads).toHaveBeenCalledTimes(1)
    })
    expect(listForThreads).toHaveBeenCalledWith([1, 2, 3, 4, 5])
    expect(screen.getByRole('list', { name: 'Series queue' })).toBeInTheDocument()
  })

  it('excludes completed threads from the batched crossover request', async () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        activeThread(1, 'Saga'),
        { ...activeThread(99, 'Finished Series'), status: 'completed' },
      ],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })

    renderQueue()

    await waitFor(() => {
      expect(listForThreads).toHaveBeenCalledWith([1])
    })
    expect(listForThreads).toHaveBeenCalledTimes(1)
  })

  it('renders each card with the memberships resolved by the single batched request', async () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [activeThread(1, 'Saga'), activeThread(2, 'Spawn')],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })
    listForThreads.mockResolvedValue({
      1: [{ id: 11, name: 'Rotworld' }],
      2: [{ id: 12, name: 'Night of the Owls' }],
    })

    renderQueue()

    expect(await screen.findByRole('link', { name: 'Rotworld' })).toHaveAttribute(
      'href',
      '/crossovers?group=11',
    )
    expect(screen.getByRole('link', { name: 'Night of the Owls' })).toHaveAttribute(
      'href',
      '/crossovers?group=12',
    )
    // Still one request total, even though two cards display crossover tags.
    expect(listForThreads).toHaveBeenCalledTimes(1)
  })

  it('does not issue a crossover request for an empty queue', async () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      nextPageToken: null,
      loadMore: vi.fn().mockResolvedValue(undefined),
    })

    renderQueue()

    expect(screen.getByTestId('queue-empty')).toBeInTheDocument()
    expect(listForThreads).not.toHaveBeenCalled()
  })
})