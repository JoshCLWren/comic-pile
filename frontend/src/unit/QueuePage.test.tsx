import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { CollectionProvider } from '../contexts/CollectionContext'
import { ToastProvider } from '../contexts/ToastContext'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
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

vi.mock('../contexts/CollectionContext', () => ({
  CollectionProvider: ({ children }) => children,
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

vi.mock('../contexts/ToastContext', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}))

const mockedUseThreads = vi.mocked(useThreads) as any
const mockedUseCreateThread = vi.mocked(useCreateThread) as any
const mockedUseUpdateThread = vi.mocked(useUpdateThread) as any
const mockedUseDeleteThread = vi.mocked(useDeleteThread) as any
const mockedUseReactivateThread = vi.mocked(useReactivateThread) as any
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
const mockedUseMoveToPosition = vi.mocked(useMoveToPosition) as any
const mockedUseSession = vi.mocked(useSession) as any
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
  mockedUseSession.mockReturnValue({
    data: { snoozed_threads: [] },
    refetch: vi.fn(),
  })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
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

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('Descender')).toBeInTheDocument()
  expect(screen.getByText('#1')).toBeInTheDocument()

  const addButtons = screen.getAllByRole('button', { name: /add thread/i })
  await user.click(addButtons[0])
  expect(screen.getByRole('heading', { name: /create thread/i })).toBeInTheDocument()
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

  it('opens action sheet when clicking thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    expect(threadCard).toBeInTheDocument()
    if (!threadCard) {
      throw new Error('Thread card not found')
    }

    await user.click(threadCard)
    expect(screen.getByText('Read Now')).toBeInTheDocument()
    expect(screen.getByText('Move to Front')).toBeInTheDocument()
    expect(screen.getByText('Move to Back')).toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(screen.getByText('Edit Thread')).toBeInTheDocument()
  })

  it('calls snooze mutation when thread is not snoozed and snooze action is clicked', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    if (!threadCard) {
      throw new Error('Thread card not found')
    }
    await user.click(threadCard)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    expect(mockSnoozeMutation.mutate).toHaveBeenCalled()
    expect(mockUnsnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('calls unsnooze mutation when thread is snoozed and unsnooze action is clicked', async () => {
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

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    if (!threadCard) {
      throw new Error('Thread card not found')
    }
    await user.click(threadCard)

    const unsnoozeButton = screen.getByText('Unsnooze')
    await user.click(unsnoozeButton)

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

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    if (!threadCard) {
      throw new Error('Thread card not found')
    }
    await user.click(threadCard)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetch).toHaveBeenCalled()
    })
  })
})

describe('Keyboard Accessibility', () => {
  it('opens action sheet when pressing Enter on thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    if (!threadCard) {
      throw new Error('Thread card not found')
    }
    threadCard.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })

  it('opens action sheet when pressing Space on thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <ToastProvider>
          <QueuePage />
        </ToastProvider>
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement | null
    if (!threadCard) {
      throw new Error('Thread card not found')
    }
    threadCard.focus()
    await user.keyboard(' ')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })
})
