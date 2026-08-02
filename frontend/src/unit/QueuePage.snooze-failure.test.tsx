import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
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
  collectionsApi: { list: vi.fn().mockResolvedValue([]) },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    create: vi.fn().mockResolvedValue({ issues: [] }),
    markRead: vi.fn().mockResolvedValue(undefined),
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/CollectionContext', () => ({
  CollectionProvider: ({ children }: { children: ReactNode }) => children,
  useCollections: vi.fn().mockReturnValue({
    collections: [],
    activeCollectionId: null,
    activeCollection: null,
    setActiveCollectionId: vi.fn(),
    createCollection: vi.fn(),
    updateCollection: vi.fn(),
    deleteCollection: vi.fn(),
    moveCollection: vi.fn(),
    isLoading: false,
  }),
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
}))

const mockedUseThreads = vi.mocked(useThreads) as any
const mockedUseSession = vi.mocked(useSession) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any

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
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useBugReportRestore).mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  } as any)
})

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
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>,
  )

  await user.click(screen.getAllByLabelText('Snooze')[0])

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to snooze thread: Snooze unavailable')
  })
  expect(snooze).toHaveBeenCalledOnce()
  expect(refetchSession).not.toHaveBeenCalled()
  expect(refetchThreads).not.toHaveBeenCalled()
})
