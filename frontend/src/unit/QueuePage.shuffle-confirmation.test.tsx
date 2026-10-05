import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
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

vi.mock('window', async importOriginal => {
  const original = await importOriginal()
  return {
    ...original,
    confirm: vi.fn(),
  }
})

describe('Queue shuffle confirmation', () => {
  it('does not shuffle when user cancels the confirmation dialog', async () => {
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

    const shuffleButton = screen.getByRole('button', { name: 'Shuffle' })
    expect(shuffleButton).toBeEnabled()

    // Simulate user clicking shuffle and canceling the confirmation
    ;(window.confirm as ReturnType<typeof vi.fn>).mockReturnValueOnce(false)
    await act(async () => {
      await shuffleButton.click()
    })

    expect(mockedUseShuffleQueue.mutate).not.toHaveBeenCalled()
  })

  it('shuffles when user confirms the confirmation dialog', async () => {
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

    const shuffleButton = screen.getByRole('button', { name: 'Shuffle' })
    expect(shuffleButton).toBeEnabled()

    // Simulate user clicking shuffle and confirming
    ;(window.confirm as ReturnType<typeof vi.fn>).mockReturnValueOnce(true)
    await act(async () => {
      await shuffleButton.click()
    })

    expect(mockedUseShuffleQueue.mutate).toHaveBeenCalledTimes(1)
  })
})