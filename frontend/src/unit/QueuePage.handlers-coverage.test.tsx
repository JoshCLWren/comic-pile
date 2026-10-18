import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter, MemoryRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { useCreateThread, useUpdateThread, useDeleteThread, useReactivateThread } from '../hooks/useThread'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useQueueThreads, useShuffleQueue, useRestoreThread, useExcludedThreads } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useQueueBlockingInfo } from '../hooks/useQueueBlockingInfo'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { useToast } from '../contexts/useToast'

// Mock implementations for hooks and services
const mockUseCreateThread = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseUpdateThread = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseDeleteThread = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseReactivateThread = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseExcludeThread = { mutate: vi.fn(), isPending: false, isError: false }

const mockUseMoveToPosition = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseMoveToFront = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseMoveToBack = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseShuffleQueue = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseRestoreThread = { mutate: vi.fn(), isPending: false, isError: false }

const mockUseQueueThreads = {
  data: [],
  isPending: false,
  isError: false,
  refetch: vi.fn(),
  nextPageToken: null,
  loadMore: vi.fn()
}

const mockUseExcludedThreads = {
  threads: [],
  isPending: false,
  isError: false
}

const mockUseSession = {
  data: { snoozed_threads: [] },
  refetch: vi.fn()
}

const mockUseSnooze = { mutate: vi.fn(), isPending: false, isError: false }
const mockUseUnsnooze = { mutate: vi.fn(), isPending: false, isError: false }

const mockUseQueueBlockingInfo = vi.fn(() => ({}))

const mockThreadsApi = {
  setPending: vi.fn(),
  // Add other methods as needed by tests
}

const mockDependenciesApi = {
  listBlockedThreadIds: vi.fn(),
  getBlockingInfo: vi.fn()
}

const mockIssuesApi = {
  create: vi.fn(),
  markRead: vi.fn(),
  bulkMarkRead: vi.fn(),
  bulkMarkUnread: vi.fn(),
  migrateThread: vi.fn()
}

const mockUseBugReportRestore = {
  setRestoreAction: vi.fn(),
  clearRestoreAction: vi.fn()
}

const mockUseToast = {
  showToast: vi.fn(),
  removeToast: vi.fn(),
  toasts: []
}

// Mock components
const MockQueueThreadCard = ({ onCardClick, onDragStart, onDragOver, onDrop, onDragEnd, onRead, onEdit, onSnooze, onDelete, onMoveToFront, onMoveToBack, onReposition, onEdit: onEditModal, onDependencies }: any) => (
  <article>
    <button onClick={onCardClick}>card callback</button>
    <button onClick={() => (onDragStart as (event: unknown) => void)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } )}>drag start</button>
    <button onClick={() => (onDragOver as (event: unknown) => void)({ preventDefault: vi.fn() } )}>drag over</button>
    <button onClick={() => (onDrop as (event: unknown) => void)({ preventDefault: vi.fn() } )}>drop</button>
    <button onClick={onDragEnd}>drag end</button>
    <button onClick={onRead}>read callback</button>
    <button onClick={onEdit}>edit callback</button>
    <button onClick={onSnooze}>snooze callback</button>
    <button onClick={onDelete}>delete callback</button>
    <button onClick={onMoveToFront}>front callback</button>
    <button onClick={onMoveToBack}>back callback</button>
    <button onClick={onReposition}>reposition callback</button>
    <button onClick={onEditModal}>edit modal callback</button>
    <button onClick={onDependencies}>dependencies callback</button>
  </article>
)

const MockModal = ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) =>
  isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null

const MockPositionSlider = ({ onPositionSelect, onCancel }: { onPositionSelect: (n: number) => void; onCancel: () => void }) => (
  <div>
    <button onClick={() => onPositionSelect(0)}>invalid position</button>
    <button onClick={() => onPositionSelect(1)}>confirm position</button>
    <button onClick={onCancel}>cancel position</button>
  </div>
)

const MockDependencyBuilder = ({ onClose, onChanged }: { onClose: () => void; onChanged: () => Promise<void> }) => (
  <div>
    <button onClick={onClose}>close dependencies</button>
    <button onClick={() => onChanged()}>dependency changed</button>
  </div>
)

const MockIssueToggleList = () => <div>issue list</div>

const MockVirtualizedThreadList = ({ threads, renderItem }: { threads: any[]; renderItem: (thread: any, index: number) => React.ReactNode }) => (
  <div data-testid="queue-thread-list">
    {threads.map((thread, index) => renderItem(thread, index))}
  </div>
)

const MockMigrationDialog = ({ onComplete, onSkip, onClose }: { onComplete: (thread: never) => void; onSkip: () => void; onClose: () => void }) => (
  <div>
    <button onClick={() => onComplete({ id: 1, title: 'Saga' } as never)}>complete migration</button>
    <button onClick={onSkip}>skip migration</button>
    <button onClick={onClose}>close migration</button>
  </div>
)

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('alert', vi.fn())
  
  // Mock the hook return values
  vi.mocked(useCreateThread).mockReturnValue(mockUseCreateThread)
  vi.mocked(useUpdateThread).mockReturnValue(mockUseUpdateThread)
  vi.mocked(useDeleteThread).mockReturnValue(mockUseDeleteThread)
  vi.mocked(useReactivateThread).mockReturnValue(mockUseReactivateThread)
  
  vi.mocked(useMoveToPosition).mockReturnValue(mockUseMoveToPosition)
  vi.mocked(useMoveToFront).mockReturnValue(mockUseMoveToFront)
  vi.mocked(useMoveToBack).mockReturnValue(mockUseMoveToBack)
  vi.mocked(useShuffleQueue).mockReturnValue(mockUseShuffleQueue)
  vi.mocked(useRestoreThread).mockReturnValue(mockUseRestoreThread)
  
  vi.mocked(useQueueThreads).mockReturnValue(mockUseQueueThreads)
  vi.mocked(useExcludedThreads).mockReturnValue(mockUseExcludedThreads)
  
  vi.mocked(useSession).mockReturnValue(mockUseSession)
  
  vi.mocked(useSnooze).mockReturnValue(mockUseSnooze)
  vi.mocked(useUnsnooze).mockReturnValue(mockUseUnsnooze)
  
  vi.mocked(useQueueBlockingInfo).mockReturnValue(mockUseQueueBlockingInfo)
  
  // Mock the service APIs
  vi.mocked(threadsApi).mockImplementation(() => mockThreadsApi)
  vi.mocked(dependenciesApi).mockImplementation(() => mockDependenciesApi)
  vi.mocked(issuesApi).mockImplementation(() => mockIssuesApi)
  
  // Mock context hooks
  vi.mocked(useBugReportRestore).mockReturnValue(mockUseBugReportRestore)
  vi.mocked(useToast).mockReturnValue(mockUseToast)
})

const thread = { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 3, total_issues: null, created_at: '2024-01-01' }
const completed = { id: 2, title: 'Done', format: 'Comic', status: 'completed', queue_position: 0, issues_remaining: 0, total_issues: 3, created_at: '2023-01-01' }
const mocks = { refetch: vi.fn(), refetchSession: vi.fn(), mutate: vi.fn() }

function renderPage() {
  return render(<BrowserRouter><QueuePage /></BrowserRouter>)
}

describe('QueuePage callback coverage', () => {
  it('runs card callbacks and closes the dependency flow', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByText('card callback'))
    await user.click(screen.getByText('drag start'))
    await user.click(screen.getByText('drag over'))
    await user.click(screen.getByText('drop'))
    await user.click(screen.getByText('drag end'))
    await user.click(screen.getByText('read callback'))
    await user.click(screen.getByText('edit callback'))
    await user.click(screen.getByText('snooze callback'))
    await user.click(screen.getByText('delete callback'))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('back callback'))
    await user.click(screen.getByText('dependencies callback'))
    await user.click(screen.getByText('dependency changed'))
    await user.click(screen.getByText('close dependencies'))
    expect(mocks.mutate).toHaveBeenCalled()
  })

  it('covers action errors, rejected actions, and reposition validation', async () => {
    const error = new Error('operation failed')
    mocks.mutate.mockRejectedValue(error)
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByText('read callback'))
    await user.click(screen.getByText('snooze callback'))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByText('invalid position'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
    await user.click(screen.getByText('confirm position'))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByText('cancel position'))
  })

  it('submits create, edit, reactivation, and migration dialog flows', async () => {
    const user = userEvent.setup()
    mocks.mutate.mockResolvedValue({ id: 9 })
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'New')
    await user.type(screen.getByLabelText('Issues'), '1-2')
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())

    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    await user.click(screen.getByText('skip migration'))
    expect(mocks.mutate).toHaveBeenCalled()
  })

  it('covers blocked-state failures, complex issue creation, and mutation failures', async () => {
    const user = userEvent.setup()
    vi.mocked(dependenciesApi.listBlockedThreadIds).mockRejectedValueOnce(new Error('blocked lookup failed'))
    vi.mocked(issuesApi.create).mockRejectedValueOnce(new Error('issue create failed'))
    mocks.mutate.mockResolvedValueOnce({ id: 9 })
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Complex')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('issue create failed')))
    mocks.mutate.mockRejectedValue(new Error('mutation failed'))
    await user.click(screen.getByText('snooze callback'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
    await user.click(screen.getByText('delete callback'))
    await waitFor(() => expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /delete series/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('mutation failed'))
  })

  it('covers migrated edit fields, location-driven create, and migration refresh failure', async () => {
    const user = userEvent.setup()
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: [{ ...thread, total_issues: 4 }] as never, isPending: false, refetch: mocks.refetch } as never)
    mocks.refetch.mockRejectedValueOnce(new Error('refresh after migration failed'))
    renderPage()
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByText('issue list')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    expect(screen.queryByText('issue list')).not.toBeInTheDocument()
  })

  it('persists a drag reorder between two active threads', async () => {
    const second = { ...thread, id: 3, title: 'Second', queue_position: 2 }
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: [thread, second] as never, isPending: false, refetch: mocks.refetch } as never)
    mocks.mutate.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByText('drag start')[0]!)
    await user.click(screen.getAllByText('drag over')[1]!)
    await user.click(screen.getAllByText('drop')[1]!)
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalledWith({ id: 1, position: 2 }))
  })

  it('completes and closes migration dialogs, including refresh failures', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    mocks.refetchSession.mockRejectedValueOnce(new Error('refresh failed'))
    await user.click(screen.getByText('complete migration'))
    await waitFor(() => expect(alert).toHaveBeenCalledWith('Failed to refresh data. Please refresh the page.'))

    await user.click(screen.getByRole('button', { name: /close modal/i }))
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    await user.click(screen.getByText('close migration'))
    expect(screen.queryByText('complete migration')).not.toBeInTheDocument()
  })

  it('opens a modal requested through router location state', async () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/queue', state: { openCreate: true } }]}><QueuePage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument())
  })

  it('uses the virtualized queue renderer for large queues', () => {
    const manyThreads = Array.from({ length: 51 }, (_, index) => ({ ...thread, id: index + 1, queue_position: index + 1 }))
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: manyThreads as never, isPending: false, refetch: mocks.refetch } as never)
    renderPage()
    expect(screen.getAllByText('card callback')).toHaveLength(51)
  })

  it('shows issue preview errors and creates complex ranges with read markers', async () => {
    const user = userEvent.setup()
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(issuesApi.create).mockResolvedValue({ issues: [{ id: 21, issue_number: 'Annual 1' }] } as never)
    mocks.mutate.mockResolvedValueOnce({ id: 9 })
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Annuals')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.type(screen.getByLabelText(/Issues already read/i), '1')
    expect(screen.getByText(/Will create/)).toBeInTheDocument()
    expect(screen.queryByTestId('issue-parse-warnings')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() => expect(issuesApi.bulkMarkRead).toHaveBeenCalledWith([21]))
  })

  it('warns that unparseable issues input becomes a literal issue name (#3262)', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Garbage')
    await user.type(screen.getByLabelText('Issues'), 'xyz')
    await waitFor(() => expect(screen.getByText(/Will create 1 issue/)).toBeInTheDocument())
    expect(
      screen.getByText("Couldn't parse 'xyz' — it will be created as a literal issue name"),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create series/i })).toBeEnabled()
  })

  it('disables create submit while the issue range is invalid', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Broken Range')
    await user.type(screen.getByLabelText('Issues'), '8-2')
    const createButton = screen.getByRole('button', { name: /create series/i })
    await waitFor(() => expect(createButton).toBeDisabled())
    await user.click(createButton)
    expect(mocks.mutate).not.toHaveBeenCalled()
    expect(alert).not.toHaveBeenCalled()
    await user.clear(screen.getByLabelText('Issues'))
    await user.type(screen.getByLabelText('Issues'), '2-8')
    await waitFor(() => expect(createButton).not.toBeDisabled())
  })

  it('alerts the user when create submit is attempted with an invalid issue range', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Broken Range')
    await user.type(screen.getByLabelText('Issues'), '8-2')
    const createButton = screen.getByRole('button', { name: /create series/i })
    await waitFor(() => expect(createButton).toBeDisabled())
    // The disabled submit button blocks pointer submission (#3108), so the
    // handler's parse-error guard is reached through a direct form submit.
    fireEvent.submit(createButton.closest('form')!)
    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith(expect.stringContaining('Failed to create series')),
    )
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it('loads mixed blocking reasons and leaves a blank reactivation selection untouched', async () => {
    vi.mocked(dependenciesApi.listBlockedThreadIds).mockResolvedValue([1, 3])
    vi.mocked(dependenciesApi.getBlockingInfo).mockResolvedValueOnce({ blocking_reasons: ['Finish Saga'], is_blocked: true }).mockRejectedValueOnce(new Error('reason failed'))
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    const form = screen.getByRole('button', { name: /add to queue/i }).closest('form')!
    fireEvent.submit(form)
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it('covers queue sorting, filtering, empty states, and router edit state', async () => {
    const user = userEvent.setup()
    vi.mocked(useQueueThreads).mockImplementation((searchTerm) => {
      let data: { id: number; title: string; format: string; status: string; queue_position: number; issues_remaining: number; total_issues: null; created_at: string; is_blocked?: boolean; blocking_reasons?: never[]; notes?: string }[] = []
      if (searchTerm !== 'missing') {
        data = [
          { ...thread, title: 'Zeta', created_at: '2024-01-01' },
          { ...thread, id: 3, title: 'Alpha', queue_position: 2, created_at: '2025-01-01' },
        ]
      }
      // SAFETY: mock return object satisfies the hook return type; as never bridges the type gap
      return {
        // SAFETY: as never is used for type narrowing in mock data
        // SAFETY: mock data shape satisfies the hook return type; as never bridges the type gap
        data: data as never,
        isPending: false,
        refetch: mocks.refetch,
        // SAFETY: as never is used for type narrowing in mock data
        // SAFETY: mock return object satisfies the hook return type; as never bridges the type gap
      } as never
    })
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Title' }))
    await user.click(screen.getByRole('button', { name: 'Recently added' }))
    await user.type(screen.getByPlaceholderText('Search...'), 'missing')
    // Search is debounced (300ms) so the parent query only commits after the delay.
    await waitFor(() => expect(screen.getByText('No active series match your search')).toBeInTheDocument(), { timeout: 2000 })
    await user.clear(screen.getByPlaceholderText('Search...'))
    await waitFor(() => expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument(), { timeout: 2000 })

    render(<MemoryRouter initialEntries={[{ pathname: '/queue', state: { editThreadId: 1 } }]}><QueuePage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('heading', { name: /edit series/i })).toBeInTheDocument())
  })

  it('exercises controlled form fields and modal close callbacks', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.selectOptions(screen.getByLabelText('Format'), 'Graphic Novel')
    await user.clear(screen.getByLabelText('Issues already read (optional)'))
    await user.type(screen.getByLabelText('Issues already read (optional)'), '2')
    await user.type(screen.getByLabelText('Notes'), 'remember this')
    await user.click(screen.getByRole('button', { name: 'close modal' }))

    await user.click(screen.getByText('edit modal callback'))
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Edited Saga')
    await user.selectOptions(screen.getByLabelText('Format'), 'Manga')
    await user.clear(screen.getByLabelText('Issues Remaining'))
    await user.type(screen.getByLabelText('Issues Remaining'), '4')
    await user.type(screen.getByLabelText('Notes'), 'updated')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    const issuesToAdd = screen.getByRole('spinbutton')
    await user.clear(issuesToAdd)
    await user.type(issuesToAdd, '3')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())

    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[1]!)
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByRole('button', { name: /close modal/i }))
  })

  it('does not render collection creation or editing controls', () => {
    renderPage()
    expect(screen.queryByRole('button', { name: /create new collection/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /create collection/i })).not.toBeInTheDocument()
  })

  it('handles loading, empty active queues, and failed queue mutations', async () => {
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: undefined, isPending: true, refetch: mocks.refetch } as never)
    const { unmount } = renderPage()
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    unmount()

    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: [completed] as never, isPending: false, refetch: mocks.refetch } as never)
    const user = userEvent.setup()
    renderPage()
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    expect(screen.getByTestId('queue-empty-add-series')).toBeInTheDocument()
    await user.click(screen.getByTestId('queue-empty-add-series'))
    expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    mocks.mutate.mockRejectedValue(new Error('reactivate failed'))
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())
  })

  it('covers delete confirmation, move failures, and no-op drops', async () => {
    const user = userEvent.setup()
    const error = new Error('mutation failed')
    mocks.mutate.mockRejectedValue(error)
    renderPage()
    await user.click(screen.getByText('delete callback'))
    expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
    expect(mocks.mutate).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('heading', { name: /delete series/i })).not.toBeInTheDocument()
    await user.click(screen.getByText('delete callback'))
    await user.click(screen.getByRole('button', { name: /delete series/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalledWith(1))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('back callback'))
    await user.click(screen.getByText('drop'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
  })

  it('confirms before shuffling and reports a failed shuffle (#3109)', async () => {
    const user = userEvent.setup()
    // SAFETY: two active series keep the SHUFFLE control enabled; as never satisfies the hook return type
    vi.mocked(useQueueThreads).mockReturnValue({
      data: [thread, { ...thread, id: 3, title: 'Spawn' }] as never,
      activeCount: 2,
      isPending: false,
      isError: false,
      refetch: mocks.refetch,
      nextPageToken: null,
      loadMore: vi.fn(),
    } as never)
    mocks.mutate.mockRejectedValue(new Error('shuffle failed'))
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    expect(screen.getByRole('heading', { name: /shuffle queue/i })).toBeInTheDocument()
    expect(mocks.mutate).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('confirm-shuffle-queue'))
    await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('shuffle')))
  })

  it('uses snoozed and blocked card branches and reports blocked reads', async () => {
    const user = userEvent.setup()
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useSession).mockReturnValue({ data: { snoozed_threads: [{ id: 1 }] }, refetch: mocks.refetchSession } as never)
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useQueueThreads).mockReturnValue({ data: [{ ...thread, is_blocked: true }] as never, isPending: false, refetch: mocks.refetch } as never)
    vi.mocked(dependenciesApi.listBlockedThreadIds).mockResolvedValue([1])
    vi.mocked(dependenciesApi.getBlockingInfo).mockResolvedValue({ blocking_reasons: [], is_blocked: false })
    renderPage()
    await user.click(screen.getByText('read callback'))
    expect(alert).not.toHaveBeenCalledWith(expect.stringContaining('Cannot read yet'))
    await user.click(screen.getByText('snooze callback'))
    expect(mocks.mutate).toHaveBeenCalled()
  })

  it('renders pending mutation labels for create, edit, and reactivation', async () => {
    const user = userEvent.setup()
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useCreateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial shape; as never satisfies the mock return type
    vi.mocked(useUpdateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    // SAFETY: as never is used for type narrowing in mock data
    // SAFETY: mocked hook returns partial share; as never satisfies the mock return type
    vi.mocked(useReactivateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0]!)
    expect(screen.getByRole('button', { name: 'Adding...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    expect(screen.getByRole('button', { name: 'Adding to queue...' })).toBeDisabled()
  })
})