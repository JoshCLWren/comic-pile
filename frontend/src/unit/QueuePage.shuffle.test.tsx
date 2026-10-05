import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    bulkMarkRead: vi.fn().mockResolvedValue(undefined),
    bulkMarkUnread: vi.fn().mockResolvedValue(undefined),
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseQueueThreads = vi.mocked(useQueueThreads) as any
// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue) as any

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
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useSession).mockReturnValue({ data: { snoozed_threads: [] }, refetch: vi.fn() } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: mockReturnValue accepts partial hook returns; cast to any for test flexibility
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  // SAFETY: useBugReportRestore returns a context shape; cast to any for partial stub
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as any)
})

describe('Queue shuffle availability', () => {
  it('disables shuffle when fewer than two active threads are available', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 }],
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })

    renderQueue()

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeDisabled()
  })

  it('keeps shuffle disabled while a shuffle mutation is pending', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
        { id: 2, title: 'Spawn', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 5 },
      ],
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: true })

    renderQueue()

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeDisabled()
  })

  it('enables shuffle when at least two active threads are available and no shuffle is pending', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
        { id: 2, title: 'Spawn', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 5 },
      ],
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })

    renderQueue()

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeEnabled()
  })

  it('enables shuffle from the authoritative count even when only one thread is loaded', () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 }],
      activeCount: 120,
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })

    renderQueue()

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeEnabled()
  })
})

/**
 * Issue #3109: SHUFFLE reorders the entire queue in one click, so it must be
 * confirmed before the mutation runs and cancelling must leave the queue
 * untouched.
 */
describe('Queue shuffle confirmation', () => {
  function renderShuffleableQueue(mutate: ReturnType<typeof vi.fn>) {
    mockedUseQueueThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
        { id: 2, title: 'Spawn', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 5 },
      ],
      activeCount: 2,
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate, isPending: false })

    renderQueue()
  }

  it('warns about the affected series count instead of shuffling on the first click', async () => {
    const user = userEvent.setup()
    const mutate = vi.fn().mockResolvedValue(undefined)
    renderShuffleableQueue(mutate)

    expect(screen.queryByRole('heading', { name: 'Shuffle Queue' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Shuffle' }))

    expect(screen.getByRole('heading', { name: 'Shuffle Queue' })).toBeInTheDocument()
    expect(screen.getByTestId('shuffle-queue-dialog')).toHaveTextContent(/reorders all 2 series/i)
    expect(mutate).not.toHaveBeenCalled()
  })

  it('leaves the queue untouched when the confirmation is cancelled', async () => {
    const user = userEvent.setup()
    const mutate = vi.fn().mockResolvedValue(undefined)
    renderShuffleableQueue(mutate)

    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Shuffle Queue' })).not.toBeInTheDocument(),
    )
    expect(mutate).not.toHaveBeenCalled()
  })

  it('shuffles and closes the confirmation once the reader confirms', async () => {
    const user = userEvent.setup()
    const mutate = vi.fn().mockResolvedValue(undefined)
    renderShuffleableQueue(mutate)

    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    await user.click(screen.getByTestId('confirm-shuffle-queue'))

    expect(mutate).toHaveBeenCalledTimes(1)
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Shuffle Queue' })).not.toBeInTheDocument(),
    )
  })
})
