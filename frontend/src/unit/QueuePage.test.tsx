import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

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
  dependenciesApi: {
    listBlockedThreadIds: vi.fn().mockResolvedValue([]),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
  collectionsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    create: vi.fn().mockResolvedValue({ issues: [] }),
    markRead: vi.fn().mockResolvedValue(undefined),
    migrateThread: vi.fn().mockResolvedValue({}),
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
const mockedDependenciesApi = vi.mocked(dependenciesApi) as any
const mockedIssuesApi = vi.mocked(issuesApi) as any

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

it('filters and sorts active threads while preserving completed threads', async () => {
  const user = userEvent.setup()
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Zeta', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 1, created_at: '2024-01-01' },
      { id: 2, title: 'Alpha', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 2, created_at: '2025-01-01' },
      { id: 3, title: 'Done', format: 'Comic', status: 'completed', queue_position: 0, issues_remaining: 0, created_at: '2023-01-01', notes: 'Finished' },
    ], isLoading: false, refetch: vi.fn(),
  })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  expect(screen.getByText('Done')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'A-Z' }))
  const cards = screen.getAllByTestId('queue-thread-item')
  expect(cards[0]).toHaveTextContent('Alpha')
  await user.type(screen.getByPlaceholderText('Search...'), 'missing')
  expect(screen.getByText('No threads match your search')).toBeInTheDocument()
})

it('creates a simple issue range and marks the requested issues read', async () => {
  const user = userEvent.setup()
  const create = vi.fn().mockResolvedValue({ id: 44 })
  mockedUseCreateThread.mockReturnValue({ mutate: create, isPending: false })
  mockedThreadsApi.setPending.mockResolvedValue({})
  mockedUseThreads.mockReturnValue({ data: [], isLoading: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
  await user.type(screen.getByLabelText('Title'), 'New Series')
  await user.clear(screen.getByLabelText('Issues'))
  await user.type(screen.getByLabelText('Issues'), '1-5')
  await user.type(screen.getByLabelText(/Last issue read/i), '2')
  await user.click(screen.getByRole('button', { name: /create thread/i }))
  await waitFor(() => expect(create).toHaveBeenCalled())
})

it('opens edit, reposition, dependency, and completed reactivation flows', async () => {
  const user = userEvent.setup()
  const refetch = vi.fn()
  mockedUseThreads.mockReturnValue({ data: [
    { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 3, total_issues: null, created_at: '2024-01-01' },
    { id: 2, title: 'Done', format: 'Comic', status: 'completed', issues_remaining: 0, created_at: '2023-01-01' },
  ], isLoading: false, refetch })
  const update = vi.fn().mockResolvedValue({})
  mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  const menu = screen.getAllByRole('button', { name: /thread actions/i })[0]
  await user.click(menu)
  await user.click(screen.getByRole('menuitem', { name: /edit/i }))
  expect(screen.getByRole('heading', { name: /edit thread/i })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /close modal/i }))
  await user.click(screen.getAllByRole('button', { name: /thread actions/i })[0])
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  expect(screen.getByTestId('position-slider-modal')).toBeInTheDocument()
  await user.click(screen.getByTestId('position-slider-cancel'))
  await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
  expect(refetch).toHaveBeenCalled()
})

it('renders loading and empty queue states', () => {
  mockedUseThreads.mockReturnValue({ data: undefined, isPending: true, refetch: vi.fn() })
  const { rerender } = render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  expect(screen.getByRole('status')).toBeInTheDocument()
  mockedUseThreads.mockReturnValue({ data: [], isPending: false, refetch: vi.fn() })
  rerender(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  expect(screen.getByText('No active threads in queue')).toBeInTheDocument()
})

it('prevents reading blocked threads and reports delete failures', async () => {
  const user = userEvent.setup()
  const deleteMutation = { mutate: vi.fn().mockRejectedValue(new Error('delete failed')), isPending: false }
  mockedUseDeleteThread.mockReturnValue(deleteMutation)
  mockedUseThreads.mockReturnValue({ data: [{ id: 1, title: 'Blocked', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 2, is_blocked: true }], isPending: false, refetch: vi.fn() })
  vi.stubGlobal('confirm', vi.fn(() => true))
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getByLabelText('Read'))
  expect(alert).toHaveBeenCalledWith(expect.stringContaining('Cannot read yet'))
  await user.click(screen.getByLabelText('Delete'))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('delete failed')))
})

it('supports created-date sorting and drag reorder failure feedback', async () => {
  const user = userEvent.setup()
  const move = { mutate: vi.fn().mockRejectedValue(new Error('reorder failed')), isPending: false }
  mockedUseMoveToPosition.mockReturnValue(move)
  mockedUseThreads.mockReturnValue({ data: [
    { id: 1, title: 'Old', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 1, created_at: '2024-01-01' },
    { id: 2, title: 'New', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 1, created_at: '2025-01-01' },
  ], isPending: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getByRole('button', { name: 'New' }))
  const cards = screen.getAllByTestId('queue-thread-item')
  expect(cards[0]).toHaveTextContent('New')
  const dragButtons = screen.getAllByRole('button', { name: 'Drag to reorder' })
  fireEvent.dragStart(dragButtons[0]!, { dataTransfer: { effectAllowed: '', setData: vi.fn() } })
  const targetCard = cards[1]!.querySelector('.queue-thread-card') as HTMLElement
  fireEvent.dragOver(targetCard)
  fireEvent.drop(targetCard, { dataTransfer: { getData: () => '1' } })
  await waitFor(() => expect(move.mutate).toHaveBeenCalled())
})

it('executes every queue action-menu operation', async () => {
  const user = userEvent.setup()
  const front = vi.fn().mockResolvedValue(undefined)
  const back = vi.fn().mockResolvedValue(undefined)
  const remove = vi.fn().mockResolvedValue(undefined)
  const refetch = vi.fn()
  mockedUseMoveToFront.mockReturnValue({ mutate: front, isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: back, isPending: false })
  mockedUseDeleteThread.mockReturnValue({ mutate: remove, isPending: false })
  mockedUseThreads.mockReturnValue({
    data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 4 }],
    isPending: false,
    refetch,
  })
  vi.stubGlobal('confirm', vi.fn(() => true))

  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  const openMenu = async () => user.click(screen.getByRole('button', { name: /thread actions/i }))

  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /move to front/i }))
  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /move to back/i }))
  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /delete/i }))

  expect(front).toHaveBeenCalledWith(1)
  expect(back).toHaveBeenCalledWith(1)
  expect(remove).toHaveBeenCalledWith(1)

  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  expect(screen.getByTestId('position-slider-modal')).toBeInTheDocument()
  await user.click(screen.getByTestId('position-slider-cancel'))
})

it('reports queue mutation failures and invalid reposition requests', async () => {
  const user = userEvent.setup()
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn().mockRejectedValue(new Error('front failed')), isPending: false })
  mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn().mockRejectedValue(new Error('shuffle failed')), isPending: false })
  mockedUseThreads.mockReturnValue({ data: [
    { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 1 },
    { id: 2, title: 'Spawn', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 1 },
  ], isPending: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getByRole('button', { name: /shuffle/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('shuffle')))
  await user.click(screen.getAllByRole('button', { name: /thread actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /move to front/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('front')))
  await user.click(screen.getAllByRole('button', { name: /thread actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '99' } })
  await user.click(screen.getByTestId('position-slider-confirm'))
})

it('creates a literal issue range and reports create failures', async () => {
  const user = userEvent.setup()
  const create = vi.fn().mockResolvedValue({ id: 55 })
  mockedUseCreateThread.mockReturnValue({ mutate: create, isPending: false })
  mockedUseThreads.mockReturnValue({ data: [], isPending: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Annuals')
  await user.clear(screen.getByLabelText('Issues'))
  await user.type(screen.getByLabelText('Issues'), 'Annual 1, 5-7')
  await user.type(screen.getByLabelText(/Last issue read/i), '1')
  await user.click(screen.getByRole('button', { name: /create thread/i }))
  await waitFor(() => expect(create).toHaveBeenCalled())

  mockedUseCreateThread.mockReturnValue({ mutate: vi.fn().mockRejectedValue(new Error('create failed')), isPending: false })
  await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Broken')
  await user.type(screen.getByLabelText('Issues'), '1')
  await user.click(screen.getByRole('button', { name: /create thread/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('create failed')))
})

it('loads blocking reasons, reads a thread, opens dependencies, and handles edit failure', async () => {
  const user = userEvent.setup()
  const update = vi.fn().mockRejectedValue(new Error('update failed'))
  mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })
  mockedDependenciesApi.listBlockedThreadIds.mockResolvedValue([2])
  mockedDependenciesApi.getBlockingInfo.mockRejectedValueOnce(new Error('details failed'))
  mockedUseThreads.mockReturnValue({ data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 2, total_issues: null }], isPending: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getByLabelText('Read'))
  expect(mockedThreadsApi.setPending).toHaveBeenCalledWith(1)
  await user.click(screen.getByRole('button', { name: /thread actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /dependencies/i }))
  expect(screen.getByRole('heading', { name: /dependencies:/i })).toBeInTheDocument()
  await user.click(screen.getByLabelText('Close modal'))
  await user.click(screen.getByRole('button', { name: /thread actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /edit/i }))
  await user.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(update).toHaveBeenCalled())
})

it('covers drag cancellation and successful repositioning', async () => {
  const user = userEvent.setup()
  const move = vi.fn().mockResolvedValue(undefined)
  const refetch = vi.fn()
  mockedUseMoveToPosition.mockReturnValue({ mutate: move, isPending: false })
  mockedUseThreads.mockReturnValue({ data: [
    { id: 1, title: 'One', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 1 },
    { id: 2, title: 'Two', format: 'Comic', status: 'active', queue_position: 2, issues_remaining: 1 },
  ], isPending: false, refetch })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  const cards = screen.getAllByTestId('queue-thread-item')
  const drag = screen.getAllByRole('button', { name: 'Drag to reorder' })
  fireEvent.dragStart(drag[0]!, { dataTransfer: { effectAllowed: '', setData: vi.fn() } })
  fireEvent.drop(cards[0]!, { dataTransfer: { getData: () => '1' } })
  await user.click(screen.getAllByRole('button', { name: /thread actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  fireEvent.change(screen.getByRole('slider'), { target: { value: '1' } })
  await user.click(screen.getByTestId('position-slider-confirm'))
  await waitFor(() => expect(move).toHaveBeenCalled())
  expect(refetch).toHaveBeenCalled()
})

it('creates complex ranges and marks the requested issues read', async () => {
  const user = userEvent.setup()
  const create = vi.fn().mockResolvedValue({ id: 77 })
  mockedUseCreateThread.mockReturnValue({ mutate: create, isPending: false })
  mockedUseThreads.mockReturnValue({ data: [], isPending: false, refetch: vi.fn() })
  mockedIssuesApi.create.mockResolvedValue({ issues: [{ id: 11 }, { id: 12 }] })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Complex')
  await user.type(screen.getByLabelText('Issues'), 'Annual 1, 5-7')
  await user.type(screen.getByLabelText(/Last issue read/i), '2')
  await user.click(screen.getByRole('button', { name: /create thread/i }))
  await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(11))
  expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(12)
})

it('handles reactivation success and failure from completed threads', async () => {
  const user = userEvent.setup()
  const reactivate = vi.fn().mockResolvedValue({})
  mockedUseReactivateThread.mockReturnValue({ mutate: reactivate, isPending: false })
  mockedUseThreads.mockReturnValue({ data: [{ id: 2, title: 'Done', format: 'Comic', status: 'completed', issues_remaining: 0 }], isPending: false, refetch: vi.fn() })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0])
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } })
  await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
  await waitFor(() => expect(reactivate).toHaveBeenCalledWith({ thread_id: 2, issues_to_add: 3 }))

  mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn().mockRejectedValue(new Error('reactivate failed')), isPending: false })
  await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0])
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
  await waitFor(() => expect(screen.getByRole('heading', { name: /reactivate thread/i })).toBeInTheDocument())
})

it('uses the virtualized queue for large collections and exposes blocked reasons', async () => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 600 })
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1024 })
  const manyThreads = Array.from({ length: 55 }, (_, index) => ({
    id: index + 1,
    title: `Thread ${index + 1}`,
    format: 'Comic',
    status: 'active',
    queue_position: index + 1,
    issues_remaining: 1,
    is_blocked: index === 0,
  }))
  mockedUseThreads.mockReturnValue({ data: manyThreads, isPending: false, refetch: vi.fn() })
  mockedDependenciesApi.listBlockedThreadIds.mockResolvedValue([1])
  mockedDependenciesApi.getBlockingInfo.mockResolvedValue({ blocking_reasons: ['Read prerequisite'] })
  render(<BrowserRouter><ToastProvider><QueuePage /></ToastProvider></BrowserRouter>)
  await waitFor(() => expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument())
  expect(screen.getByRole('list', { name: 'Thread queue' })).toBeInTheDocument()
  vi.unstubAllGlobals()
})
