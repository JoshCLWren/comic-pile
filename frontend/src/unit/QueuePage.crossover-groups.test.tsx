import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { dependencyGroupsApi, type DependencyGroupSummary } from '../services/api-dependency-groups'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../hooks/useThread'
import {
  useMoveToBack,
  useMoveToFront,
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
  },
  {
    id: 4,
    title: 'Finished Series',
    format: 'Comic',
    status: 'completed',
    queue_position: 0,
    issues_remaining: 0,
    total_issues: 12,
  },
]

const ROTWORLD: DependencyGroupSummary[] = [{ id: 11, name: 'Rotworld' }]

const originalListForThreads = dependencyGroupsApi.listForThreads
const listForThreads = vi.fn<CrossoverGroupsApi['listForThreads']>()

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('alert', vi.fn())
  dependencyGroupsApi.listForThreads = listForThreads

  vi.mocked(useQueueThreads).mockReturnValue({
    data: ACTIVE_THREADS,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    nextPageToken: null,
    loadMore: vi.fn(),
    activeCount: 3,
  } // SAFETY: test double matches useQueueThreads return shape
  )
  vi.mocked(useSession).mockReturnValue({
    data: { snoozed_threads: [], skipped_thread_ids: [], skipped_threads: [] },
    refetch: vi.fn(),
  } // SAFETY: test double matches useSession return shape
  )
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useCreateThread return shape
  )
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useUpdateThread return shape
  )
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useDeleteThread return shape
  )
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useReactivateThread return shape
  )
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useMoveToFront return shape
  )
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useMoveToBack return shape
  )
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useMoveToPosition return shape
  )
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useShuffleQueue return shape
  )
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useSnooze return shape
  )
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } // SAFETY: test double matches useUnsnooze return shape
  )

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
      <QueuePage />
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
