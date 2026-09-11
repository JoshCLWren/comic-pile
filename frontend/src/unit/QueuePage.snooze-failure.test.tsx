import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
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
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseQueueThreads = vi.mocked(useQueueThreads) as any
// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseSession = vi.mocked(useSession) as any
// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseSnooze = vi.mocked(useSnooze) as any
// SAFETY: vi.mocked returns mocked type; cast to any for flexible test stubs
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
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
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  // SAFETY: useBugReportRestore returns a context shape; cast to any for partial stub
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as any)
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

it('does not refresh session or threads when snooze fails', async () => {
  const refetchThreads = vi.fn()
  const refetchSession = vi.fn()
  const snooze = vi.fn().mockRejectedValue({
    response: { data: { detail: 'Snooze unavailable' } },
  })

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
    isLoading: false,
    refetch: refetchThreads,
  })
  mockedUseSession.mockReturnValue({
    data: { pending_thread_id: 1, snoozed_threads: [] },
    refetch: refetchSession,
  })
  mockedUseSnooze.mockReturnValue({ mutate: snooze, isPending: false })

  const user = userEvent.setup()
  renderQueue()

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /^snooze$/i }))

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to snooze thread: Snooze unavailable')
  })
  expect(snooze).toHaveBeenCalledOnce()
  expect(refetchSession).not.toHaveBeenCalled()
  expect(refetchThreads).not.toHaveBeenCalled()
})

it('does not refresh session or threads when unsnooze fails', async () => {
  const refetchThreads = vi.fn()
  const refetchSession = vi.fn()
  const unsnooze = vi.fn().mockRejectedValue({
    response: { data: { detail: 'Unsnooze unavailable' } },
  })

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
    isLoading: false,
    refetch: refetchThreads,
  })
  mockedUseSession.mockReturnValue({
    data: { snoozed_threads: [{ id: 1 }] },
    refetch: refetchSession,
  })
  mockedUseUnsnooze.mockReturnValue({ mutate: unsnooze, isPending: false })

  const user = userEvent.setup()
  renderQueue()

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /^unsnooze$/i }))

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to unsnooze thread: Unsnooze unavailable')
  })
  expect(unsnooze).toHaveBeenCalledWith(1)
  expect(refetchSession).not.toHaveBeenCalled()
  expect(refetchThreads).not.toHaveBeenCalled()
})

it('keeps snooze disabled before session data has loaded', async () => {
  const refetchThreads = vi.fn()
  const refetchSession = vi.fn().mockResolvedValue(undefined)
  const snooze = vi.fn().mockResolvedValue(undefined)

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
    isLoading: false,
    refetch: refetchThreads,
  })
  mockedUseSession.mockReturnValue({
    data: undefined,
    refetch: refetchSession,
  })
  mockedUseSnooze.mockReturnValue({ mutate: snooze, isPending: false })

  const user = userEvent.setup()
  renderQueue()

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  const snoozeMenuItem = screen.getByRole('menuitem', { name: /^snooze$/i })
  expect(snoozeMenuItem).toBeDisabled()
  await user.click(snoozeMenuItem)

  expect(refetchSession).not.toHaveBeenCalled()
  expect(snooze).not.toHaveBeenCalled()
  expect(refetchThreads).not.toHaveBeenCalled()
  expect(alert).not.toHaveBeenCalled()
})