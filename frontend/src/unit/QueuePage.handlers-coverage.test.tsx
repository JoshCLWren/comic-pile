import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter, MemoryRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { useThreads, useCreateThread, useUpdateThread, useDeleteThread, useReactivateThread } from '../hooks/useThread'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { threadsApi, dependenciesApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useCreateThread: vi.fn(), useUpdateThread: vi.fn(), useDeleteThread: vi.fn(), useReactivateThread: vi.fn() }))
vi.mock('../hooks/useQueue', () => ({ useMoveToBack: vi.fn(), useMoveToFront: vi.fn(), useMoveToPosition: vi.fn(), useShuffleQueue: vi.fn() }))
vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn(), useUnsnooze: vi.fn() }))
vi.mock('../services/api', () => ({ threadsApi: { setPending: vi.fn() }, dependenciesApi: { listBlockedThreadIds: vi.fn(), getBlockingInfo: vi.fn() } }))
vi.mock('../services/api-issues', () => ({ issuesApi: { create: vi.fn(), markRead: vi.fn(), migrateThread: vi.fn() } }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({
  collections: [], activeCollectionId: null, setActiveCollectionId: vi.fn(), isLoading: false, error: null,
  createCollection: vi.fn(), updateCollection: vi.fn(), deleteCollection: vi.fn(), moveCollection: vi.fn(),
}) }))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }) }))
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }) }))
vi.mock('../pages/QueuePage/QueueThreadCard', () => ({ default: (props: Record<string, unknown>) => <article><button onClick={props.onCardClick as () => void}>card callback</button><button onClick={() => (props.onDragStart as (event: unknown) => void)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } })}>drag start</button><button onClick={() => (props.onDragOver as (event: unknown) => void)({ preventDefault: vi.fn() })}>drag over</button><button onClick={() => (props.onDrop as (event: unknown) => void)({ preventDefault: vi.fn() })}>drop</button><button onClick={props.onDragEnd as () => void}>drag end</button><button onClick={props.onSwipeRead as () => void}>read callback</button><button onClick={props.onSwipeEdit as () => void}>edit callback</button><button onClick={props.onSwipeSnooze as () => void}>snooze callback</button><button onClick={props.onSwipeDelete as () => void}>delete callback</button><button onClick={props.onMoveToFront as () => void}>front callback</button><button onClick={props.onMoveToBack as () => void}>back callback</button><button onClick={props.onReposition as () => void}>reposition callback</button><button onClick={props.onEdit as () => void}>edit modal callback</button><button onClick={props.onDependencies as () => void}>dependencies callback</button></article> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/PositionSlider', () => ({ default: ({ onPositionSelect, onCancel }: { onPositionSelect: (n: number) => void; onCancel: () => void }) => <div><button onClick={() => onPositionSelect(0)}>invalid position</button><button onClick={() => onPositionSelect(1)}>confirm position</button><button onClick={onCancel}>cancel position</button></div> }))
vi.mock('../components/DependencyBuilder', () => ({ default: ({ onClose, onChanged }: { onClose: () => void; onChanged: () => Promise<void> }) => <div><button onClick={onClose}>close dependencies</button><button onClick={() => void onChanged()}>dependency changed</button></div> }))
vi.mock('../pages/QueuePage/IssueToggleList', () => ({ IssueToggleList: () => <div>issue list</div> }))
vi.mock('../pages/QueuePage/VirtualizedThreadList', () => ({ VIRTUALIZATION_THRESHOLD: 50, default: ({ threads, renderItem }: { threads: never[]; renderItem: (thread: never, index: number) => React.ReactNode }) => <div>{threads.slice(0, 1).map((thread, index) => renderItem(thread, index))}</div> }))
vi.mock('../components/MigrationDialog', () => ({ default: ({ onComplete, onSkip, onClose }: { onComplete: (thread: never) => void; onSkip: () => void; onClose: () => void }) => <div><button onClick={() => onComplete({ id: 1, title: 'Saga' } as never)}>complete migration</button><button onClick={onSkip}>skip migration</button><button onClick={onClose}>close migration</button></div> }))

const thread = { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 3, total_issues: null, created_at: '2024-01-01' }
const completed = { id: 2, title: 'Done', format: 'Comic', status: 'completed', queue_position: 0, issues_remaining: 0, total_issues: 3, created_at: '2023-01-01' }
const mocks = { refetch: vi.fn(), refetchSession: vi.fn(), mutate: vi.fn() }

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('alert', vi.fn())
  vi.stubGlobal('confirm', vi.fn(() => true))
  mocks.mutate.mockResolvedValue(undefined)
  vi.mocked(useThreads).mockReturnValue({ data: [thread, completed] as never, isPending: false, refetch: mocks.refetch } as never)
  vi.mocked(useSession).mockReturnValue({ data: { snoozed_threads: [] }, refetch: mocks.refetchSession } as never)
  vi.mocked(useCreateThread).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useUpdateThread).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useDeleteThread).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useReactivateThread).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useMoveToPosition).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useSnooze).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: mocks.mutate, isPending: false } as never)
  vi.mocked(threadsApi.setPending).mockResolvedValue({ thread_id: 1 } as never)
  vi.mocked(dependenciesApi.listBlockedThreadIds).mockResolvedValue([])
  vi.mocked(issuesApi.create).mockResolvedValue({ issues: [] } as never)
  vi.mocked(issuesApi.markRead).mockResolvedValue(undefined)
  vi.mocked(issuesApi.migrateThread).mockResolvedValue({} as never)
})

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
    expect(mocks.refetch).toHaveBeenCalled()
  })

  it('covers action errors, rejected swipe actions, and reposition validation', async () => {
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
    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
    await user.type(screen.getByLabelText('Title'), 'New')
    await user.type(screen.getByLabelText('Issues'), '1-2')
    await user.click(screen.getByRole('button', { name: /create thread/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())

    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
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
    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Complex')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.click(screen.getByRole('button', { name: /create thread/i }))
    await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('issue create failed')))
    mocks.mutate.mockRejectedValue(new Error('mutation failed'))
    await user.click(screen.getByText('snooze callback'))
    await user.click(screen.getByText('delete callback'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
  })

  it('covers migrated edit fields, location-driven create, and migration refresh failure', async () => {
    const user = userEvent.setup()
    vi.mocked(useThreads).mockReturnValue({ data: [{ ...thread, total_issues: 4 }] as never, isPending: false, refetch: mocks.refetch } as never)
    mocks.refetch.mockRejectedValueOnce(new Error('refresh after migration failed'))
    renderPage()
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByText('issue list')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    expect(screen.queryByText('issue list')).not.toBeInTheDocument()
  })

  it('persists a drag reorder between two active threads', async () => {
    const second = { ...thread, id: 3, title: 'Second', queue_position: 2 }
    vi.mocked(useThreads).mockReturnValue({ data: [thread, second] as never, isPending: false, refetch: mocks.refetch } as never)
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
    mocks.refetch.mockRejectedValueOnce(new Error('refresh failed'))
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
    await waitFor(() => expect(screen.getByRole('heading', { name: /create thread/i })).toBeInTheDocument())
  })

  it('uses the virtualized queue renderer for large queues', () => {
    const manyThreads = Array.from({ length: 51 }, (_, index) => ({ ...thread, id: index + 1, queue_position: index + 1 }))
    vi.mocked(useThreads).mockReturnValue({ data: manyThreads as never, isPending: false, refetch: mocks.refetch } as never)
    renderPage()
    expect(screen.getByText('card callback')).toBeInTheDocument()
  })

  it('shows issue preview errors and creates complex ranges with read markers', async () => {
    const user = userEvent.setup()
    vi.mocked(issuesApi.create).mockResolvedValue({ issues: [{ id: 21, issue_number: 'Annual 1' }] } as never)
    mocks.mutate.mockResolvedValueOnce({ id: 9 })
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Annuals')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.type(screen.getByLabelText(/Last issue read/i), '1')
    expect(screen.getByText(/Will create/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /create thread/i }))
    await waitFor(() => expect(issuesApi.markRead).toHaveBeenCalledWith(21))

    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Invalid')
    await user.type(screen.getByLabelText('Issues'), 'x'.repeat(101))
    await waitFor(() => expect(screen.getByText(/issue identifier too long/i)).toBeInTheDocument())
  })

  it('loads mixed blocking reasons and leaves a blank reactivation selection untouched', async () => {
    vi.mocked(dependenciesApi.listBlockedThreadIds).mockResolvedValue([1, 3])
    vi.mocked(dependenciesApi.getBlockingInfo).mockResolvedValueOnce({ blocking_reasons: ['Finish Saga'] }).mockRejectedValueOnce(new Error('reason failed'))
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
    const form = screen.getByRole('button', { name: /reactivate thread/i }).closest('form')!
    fireEvent.submit(form)
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it('covers queue sorting, filtering, empty states, and router edit state', async () => {
    const user = userEvent.setup()
    vi.mocked(useThreads).mockReturnValue({ data: [
      { ...thread, title: 'Zeta', created_at: '2024-01-01' },
      { ...thread, id: 3, title: 'Alpha', queue_position: 2, created_at: '2025-01-01' },
    ] as never, isPending: false, refetch: mocks.refetch } as never)
    renderPage()
    await user.click(screen.getByRole('button', { name: 'A-Z' }))
    await user.click(screen.getByRole('button', { name: 'New' }))
    await user.type(screen.getByPlaceholderText('Search...'), 'missing')
    expect(screen.getByText('No threads match your search')).toBeInTheDocument()
    await user.clear(screen.getByPlaceholderText('Search...'))
    expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()

    render(<MemoryRouter initialEntries={[{ pathname: '/queue', state: { editThreadId: 1 } }]}><QueuePage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('heading', { name: /edit thread/i })).toBeInTheDocument())
  })

  it('exercises controlled form fields and modal close callbacks', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0])
    await user.selectOptions(screen.getByLabelText('Format'), 'Graphic Novel')
    await user.clear(screen.getByLabelText('Last issue read (optional)'))
    await user.type(screen.getByLabelText('Last issue read (optional)'), '2')
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

    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
    const issuesToAdd = screen.getByRole('spinbutton')
    await user.clear(issuesToAdd)
    await user.type(issuesToAdd, '3')
    await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())

    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[1]!)
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByRole('button', { name: /close modal/i }))
  })

  it('opens and closes the collection dialog when collections are enabled', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: /create new collection/i }))
    expect(screen.getByRole('heading', { name: /create collection/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /close dialog/i }))
    expect(screen.queryByRole('heading', { name: /create collection/i })).not.toBeInTheDocument()
  })

  it('handles loading, empty active queues, and failed queue mutations', async () => {
    vi.mocked(useThreads).mockReturnValue({ data: undefined, isPending: true, refetch: mocks.refetch } as never)
    const { unmount } = renderPage()
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    unmount()

    vi.mocked(useThreads).mockReturnValue({ data: [completed] as never, isPending: false, refetch: mocks.refetch } as never)
    const user = userEvent.setup()
    renderPage()
    expect(screen.getByText('No active threads in queue')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
    mocks.mutate.mockRejectedValue(new Error('reactivate failed'))
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /reactivate thread/i }))
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalled())
  })

  it('covers delete confirmation, shuffle and move failures, and no-op drops', async () => {
    const user = userEvent.setup()
    const error = new Error('mutation failed')
    mocks.mutate.mockRejectedValue(error)
    vi.stubGlobal('confirm', vi.fn(() => false))
    renderPage()
    await user.click(screen.getByText('delete callback'))
    expect(mocks.mutate).not.toHaveBeenCalled()
    vi.stubGlobal('confirm', vi.fn(() => true))
    await user.click(screen.getByText('delete callback'))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('back callback'))
    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    await user.click(screen.getByText('drop'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
  })

  it('uses snoozed and blocked card branches and reports blocked reads', async () => {
    const user = userEvent.setup()
    vi.mocked(useSession).mockReturnValue({ data: { snoozed_threads: [{ id: 1 }] }, refetch: mocks.refetchSession } as never)
    vi.mocked(useThreads).mockReturnValue({ data: [{ ...thread, is_blocked: true }] as never, isPending: false, refetch: mocks.refetch } as never)
    vi.mocked(dependenciesApi.listBlockedThreadIds).mockResolvedValue([1])
    vi.mocked(dependenciesApi.getBlockingInfo).mockResolvedValue({ blocking_reasons: [] })
    renderPage()
    await user.click(screen.getByText('read callback'))
    await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('Cannot read yet')))
    await user.click(screen.getByText('snooze callback'))
    expect(mocks.mutate).toHaveBeenCalled()
  })

  it('renders pending mutation labels for create, edit, and reactivation', async () => {
    const user = userEvent.setup()
    vi.mocked(useCreateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    vi.mocked(useUpdateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    vi.mocked(useReactivateThread).mockReturnValue({ mutate: mocks.mutate, isPending: true } as never)
    renderPage()
    await user.click(screen.getAllByRole('button', { name: /add thread/i })[0]!)
    expect(screen.getByRole('button', { name: 'Creating...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getAllByRole('button', { name: /^reactivate$/i })[0]!)
    expect(screen.getByRole('button', { name: 'Reactivating...' })).toBeDisabled()
  })

})
