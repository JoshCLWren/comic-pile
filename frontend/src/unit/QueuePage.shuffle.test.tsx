import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'
import QueuePage from '../pages/QueuePage'

vi.mock('../hooks/useThread', () => ({
  useThreads: vi.fn(),
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useDeleteThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
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

const mockedUseThreads = vi.mocked(useThreads) as any
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
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useSession).mockReturnValue({ data: { snoozed_threads: [] }, refetch: vi.fn() } as any)
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as any)
})

describe('Queue shuffle availability', () => {
  it('disables shuffle when fewer than two active threads are available', () => {
    mockedUseThreads.mockReturnValue({
      data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 }],
      isLoading: false,
      refetch: vi.fn(),
    })
    mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })

    renderQueue()

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeDisabled()
  })

  it('keeps shuffle disabled while a shuffle mutation is pending', () => {
    mockedUseThreads.mockReturnValue({
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
    mockedUseThreads.mockReturnValue({
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
})
