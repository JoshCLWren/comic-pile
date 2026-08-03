import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
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
const mockedUseSession = vi.mocked(useSession) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
  vi.mocked(useCreateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
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

  mockedUseThreads.mockReturnValue({
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
    data: { snoozed_threads: [] },
    refetch: refetchSession,
  })
  mockedUseSnooze.mockReturnValue({ mutate: snooze, isPending: false })

  const user = userEvent.setup()
  renderQueue()

  await user.click(screen.getAllByLabelText('Snooze')[0])

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

  mockedUseThreads.mockReturnValue({
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

  await user.click(screen.getAllByLabelText('Unsnooze')[0])

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to unsnooze thread: Unsnooze unavailable')
  })
  expect(unsnooze).toHaveBeenCalledWith(1)
  expect(refetchSession).not.toHaveBeenCalled()
  expect(refetchThreads).not.toHaveBeenCalled()
})

it('keeps snooze actionable before session data has loaded', async () => {
  const refetchThreads = vi.fn()
  const refetchSession = vi.fn().mockResolvedValue(undefined)
  const snooze = vi.fn().mockResolvedValue(undefined)

  mockedUseThreads.mockReturnValue({
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

  await user.click(screen.getAllByLabelText('Snooze')[0])

  await waitFor(() => {
    expect(refetchSession).toHaveBeenCalledOnce()
  })
  expect(snooze).toHaveBeenCalledOnce()
  expect(refetchThreads).not.toHaveBeenCalled()
  expect(alert).not.toHaveBeenCalled()
})
