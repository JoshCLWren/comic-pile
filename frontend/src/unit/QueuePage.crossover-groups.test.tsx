import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { ToastProvider } from '../contexts/ToastProvider'
import QueuePage from '../pages/QueuePage'
import { dependencyGroupsApi, type DependencyGroupSummary } from '../services/api-dependency-groups'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../hooks/useThread'
import {
  useMoveToFront,
  useMoveToBack,
  useMoveToPosition,
  useQueueThreads,
  useShuffleQueue,
} from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import type { CrossoverGroupsApi } from '../hooks/useCrossoverGroups'

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

vi.mock('../services/api-threads', () => ({ threadsApi: { setPending: vi.fn() } }))

vi.mock('../services/api', () => ({
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

const ACTIVE_THREADS = [
  {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    status: 'active',
    queue_position: 1,
    issues_remaining: 5,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-01-01T00:00:00Z',
    last_activity_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 2,
    title: 'Descender',
    format: 'Comic',
    status: 'active',
    queue_position: 2,
    issues_remaining: 3,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-01-01T00:00:00Z',
    last_activity_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 3,
    title: 'Y: The Last Man',
    format: 'Comic',
    status: 'active',
    queue_position: 3,
    issues_remaining: 8,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-01-01T00:00:00Z',
    last_activity_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 4,
    title: 'Finished Series',
    format: 'Comic',
    status: 'completed',
    queue_position: 0,
    issues_remaining: 0,
    total_issues: 12,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-01-01T00:00:00Z',
    last_activity_at: '2026-01-01T00:00:00Z',
  },
]

const ROTWORLD: DependencyGroupSummary[] = [{ id: 11, name: 'Rotworld' }]

const originalListForThreads = dependencyGroupsApi.listForThreads
const listForThreads = vi.fn<CrossoverGroupsApi['listForThreads']>()

/**
 * Point a module-mocked hook at the return value this test needs.
 *
 * Every `vi.mock` factory above replaces the real hook module with a bare
 * `vi.fn()` double, so the double no longer carries the production signature
 * and each test supplies only the fields `QueuePage` actually reads. The
 * helper keeps that intent in one documented place instead of casting twelve
 * mocks independently.
 */
function mockHookResult<T>(hook: unknown, value: T): void {
  // SAFETY: the `vi.mock` factories replace each hook module with a bare
  // `vi.fn()`, so `mockReturnValue` accepts any value and this cast only
  // re-types that test double rather than asserting a runtime fact.
  const hookDouble = hook as { mockReturnValue: (next: T) => void }
  hookDouble.mockReturnValue(value)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('alert', vi.fn())
  dependencyGroupsApi.listForThreads = listForThreads

  mockHookResult(useQueueThreads, {
    data: ACTIVE_THREADS,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: null,
    loadMore: vi.fn(),
    activeCount: 3,
  })
  mockHookResult(useSession, {
    data: { snoozed_threads: [] },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })
  mockHookResult(useCreateThread, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useUpdateThread, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useDeleteThread, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useReactivateThread, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useMoveToFront, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useMoveToBack, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useMoveToPosition, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useShuffleQueue, { mutate: vi.fn(), isPending: false, isError: false })
  mockHookResult(useSnooze, {
    mutate: vi.fn(),
    retryRefresh: vi.fn(),
    isPending: false,
    isError: false,
    refreshError: null,
    hasRefreshError: false,
  })
  mockHookResult(useUnsnooze, { mutate: vi.fn(), isPending: false, isError: false })

  listForThreads.mockImplementation(async (threadIds) => {
    const groups: Record<number, DependencyGroupSummary[]> = {}
    for (const threadId of threadIds) {
      groups[threadId] = threadId === 1 ? ROTWORLD : []
    }
    return groups
  })
})

afterEach(() => {
  dependencyGroupsApi.listForThreads = originalListForThreads
})

function renderPage() {
  return render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>,
  )
}

describe('QueuePage crossover group batching', () => {
  it('issues one crossover-groups request for the whole active queue, not one per card', async () => {
    renderPage()

    await screen.findByRole('link', { name: 'Rotworld' })

    expect(listForThreads).toHaveBeenCalledTimes(1)
    expect(listForThreads).toHaveBeenCalledWith([1, 2, 3])
    expect(screen.getAllByTestId('queue-thread-item')).toHaveLength(3)
  })

  it('never starts per-card crossover requests while the page-level batch is pending', async () => {
    // SAFETY: deferred resolver starts unset and is assigned once the batch promise executor runs.
    const deferred = {
      resolve: undefined as ((value: Record<number, DependencyGroupSummary[]>) => void) | undefined,
    }
    listForThreads.mockImplementation(
      () =>
        new Promise((resolve) => {
          deferred.resolve = resolve
        }),
    )

    renderPage()

    expect(await screen.findAllByText('Loading crossovers…')).toHaveLength(3)
    expect(listForThreads).toHaveBeenCalledTimes(1)

    await act(async () => {
      deferred.resolve?.({ 1: ROTWORLD, 2: [], 3: [] })
    })

    await screen.findByRole('link', { name: 'Rotworld' })
    expect(listForThreads).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Loading crossovers…')).not.toBeInTheDocument()
  })

  it('surfaces a non-blocking error state instead of falling back to per-card requests', async () => {
    listForThreads.mockRejectedValue(new Error('batch unavailable'))

    renderPage()

    expect(await screen.findAllByText('Crossovers unavailable')).toHaveLength(3)
    expect(listForThreads).toHaveBeenCalledTimes(1)
  })
})
