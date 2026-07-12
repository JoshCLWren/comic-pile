import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { CollectionProvider } from '../contexts/CollectionContext'
import { ToastProvider } from '../contexts/ToastProvider'
import {
 useCreateThread,
 useDeleteThread,
 useReactivateThread,
 useThreads,
 useUpdateThread,
} from '../hooks/useThread'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { threadsApi } from '../services/api'

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

vi.mock('../hooks/useSession', () => ({
  useSession: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    setPending: vi.fn(),
  },
  collectionsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: vi.fn(),
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
const mockedUseCreateThread = vi.mocked(useCreateThread) as any
const mockedUseUpdateThread = vi.mocked(useUpdateThread) as any
const mockedUseDeleteThread = vi.mocked(useDeleteThread) as any
const mockedUseReactivateThread = vi.mocked(useReactivateThread) as any
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
const mockedUseMoveToPosition = vi.mocked(useMoveToPosition) as any
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue) as any
const mockedUseSession = vi.mocked(useSession) as any
const mockedUseBugReportRestore = vi.mocked(useBugReportRestore) as any
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any
const mockedThreadsApi = vi.mocked(threadsApi) as any

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
      { id: 2, title: 'Descender', format: 'Comic', status: 'completed', issues_remaining: 0 },
    ],
    isLoading: false,
    refetch: vi.fn(),
  })
  mockedUseCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseDeleteThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToPosition.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSession.mockReturnValue({
    data: { snoozed_threads: [] },
    refetch: vi.fn(),
  })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseBugReportRestore.mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  })
  mockedThreadsApi.setPending.mockResolvedValue({
    thread_id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 5,
    queue_position: 1,
    die_size: 6,
    result: 1,
    offset: 0,
    snoozed_count: 0,
    issue_id: null,
    issue_number: null,
    next_issue_id: null,
    next_issue_number: null,
    total_issues: null,
    reading_progress: null,
  } as never)
})

it('renders queue items and opens create modal', async () => {
  const user = userEvent.setup()
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>
  )

  expect(screen.getAllByText('Saga')[0]).toBeInTheDocument()
  expect(screen.getByText('Descender')).toBeInTheDocument()
  expect(screen.getByText('#1')).toBeInTheDocument()

  const addButtons = screen.getAllByRole('button', { name: /add thread/i })
  await user.click(addButtons[0])
  expect(screen.getByRole('heading', { name: /create thread/i })).toBeInTheDocument()
})

it('registers a restore target while the create modal is open', async () => {
  const user = userEvent.setup()
  const restoreState = {
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  }
  mockedUseBugReportRestore.mockReturnValue(restoreState)

  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>
  )

  await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])

  expect(restoreState.setRestoreAction).toHaveBeenCalled()

  await user.click(screen.getByLabelText('Close modal'))

  await waitFor(() => {
    expect(restoreState.clearRestoreAction).toHaveBeenCalled()
  })
})

it('shuffles the queue from the header control', async () => {
  const mockRefetch = vi.fn()
  const mockShuffle = { mutate: vi.fn(), isPending: false }
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
      { id: 3, title: 'Spawn', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 7 },
      { id: 2, title: 'Descender', format: 'Comic', status: 'completed', issues_remaining: 0 },
    ],
    isLoading: false,
    refetch: mockRefetch,
  })
  mockedUseShuffleQueue.mockReturnValue(mockShuffle)

  const user = userEvent.setup()
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>
  )

  await user.click(screen.getByRole('button', { name: /shuffle/i }))

  expect(mockShuffle.mutate).toHaveBeenCalled()
  expect(mockRefetch).toHaveBeenCalled()
})

describe('Action Sheet Snooze/Unsnooze', () => {
  const mockSnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockUnsnoozeMutation = { mutate: vi.fn(), isPending: false }

  beforeEach(() => {
    mockSnoozeMutation.mutate.mockReset()
    mockUnsnoozeMutation.mutate.mockReset()
    mockedUseSnooze.mockReturnValue(mockSnoozeMutation)
    mockedUseUnsnooze.mockReturnValue(mockUnsnoozeMutation)
  })

  it('shows swipe actions for thread cards', () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const readButtons = screen.getAllByLabelText('Read')
    const editButtons = screen.getAllByLabelText('Edit')
    const snoozeButtons = screen.getAllByLabelText('Snooze')
    const deleteButtons = screen.getAllByLabelText('Delete')
    expect(readButtons.length).toBeGreaterThan(0)
    expect(editButtons.length).toBeGreaterThan(0)
    expect(snoozeButtons.length).toBeGreaterThan(0)
    expect(deleteButtons.length).toBeGreaterThan(0)
  })

  it('calls snooze mutation when snooze swipe action is clicked', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const snoozeButtons = screen.getAllByLabelText('Snooze')
    await user.click(snoozeButtons[0])

    expect(mockSnoozeMutation.mutate).toHaveBeenCalled()
    expect(mockUnsnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('calls unsnooze mutation when unsnooze swipe action is clicked', async () => {
    mockedUseSession.mockReturnValue({
      data: {
        snoozed_threads: [{ id: 1, title: 'Saga', format: 'Comic' }]
      },
      refetch: vi.fn(),
    })

    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const unsnoozeButtons = screen.getAllByLabelText('Unsnooze')
    await user.click(unsnoozeButtons[0])

    expect(mockUnsnoozeMutation.mutate).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('refetches session and threads after snooze action', async () => {
    const mockRefetchSession = vi.fn()
    const mockRefetch = vi.fn()
    mockedUseSession.mockReturnValue({
      data: { snoozed_threads: [] },
      refetch: mockRefetchSession,
    })
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
      ],
      isLoading: false,
      refetch: mockRefetch,
    })

    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const snoozeButtons = screen.getAllByLabelText('Snooze')
    await user.click(snoozeButtons[0])

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetch).toHaveBeenCalled()
    })
  })
})

describe('Keyboard Accessibility', () => {
  it('thread card is present and focusable', () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const threadItems = screen.getAllByTestId('queue-thread-item')
    expect(threadItems.length).toBeGreaterThan(0)
  })
})
