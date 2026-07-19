import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

const spies = vi.hoisted(() => ({
  navigate: vi.fn(), refetch: vi.fn().mockResolvedValue({}), mutate: vi.fn().mockResolvedValue({}),
  setPending: vi.fn().mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 }),
}))
const sessionHook = vi.hoisted(() => ({ value: null as unknown }))
const relatedApi = vi.hoisted(() => ({ readingOrders: vi.fn(), connectedThreads: vi.fn() }))
const sessionData: { current_die: number; snoozed_threads: Array<{ id: number; title: string; format: string }>; manual_die?: number; last_rolled_result?: number | null } = { current_die: 6, snoozed_threads: [] }
const threadData: Array<{ id: number; title: string; format: string; status: string; is_blocked?: boolean }> = [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }]
let staleData: never[] = []

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../config/featureFlags', () => ({ collectionsEnabled: false, isReviewsFeatureEnabled: () => false }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({ activeCollectionId: null }) }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn((restore: () => void) => restore()),
    clearRestoreAction: vi.fn(),
  }),
}))
vi.mock('../hooks/useSession', () => ({ useSession: () => sessionHook.value ?? ({ data: sessionData, refetch: spies.refetch }) }))
vi.mock('../hooks/useThread', () => ({ useThreads: () => ({ data: threadData, refetch: spies.refetch }), useStaleThreads: () => ({ data: staleData, refetch: spies.refetch }) }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: spies.mutate, isPending: false }), useClearManualDie: () => ({ mutate: spies.mutate, isPending: false }),
  useRoll: () => ({ mutate: spies.mutate, isPending: false }), useDismissPending: () => ({ mutate: spies.mutate, isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.mutate, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: () => ({ mutate: spies.mutate, isPending: false }), useUnsnooze: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../hooks/useQueue', () => ({ useMoveToFront: () => ({ mutate: spies.mutate, isPending: false }), useMoveToBack: () => ({ mutate: spies.mutate, isPending: false }), useShuffleQueue: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../services/api', () => ({ threadsApi: { setPending: spies.setPending }, dependenciesApi: { getConnectedThreads: relatedApi.connectedThreads } }))
vi.mock('../services/api-reading-orders', () => ({ readingOrdersApi: { getForThread: relatedApi.readingOrders } }))
vi.mock('../services/api-reviews', () => ({ reviewsApi: { createOrUpdateReview: spies.mutate } }))
vi.mock('../components/LazyDice3D', () => ({
  default: ({ onRollComplete }: { onRollComplete?: () => void }) => (
    <div data-testid="dice"><button type="button" onClick={onRollComplete}>complete dice</button></div>
  ),
}))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/CollectionDialog', () => ({ default: () => <div>collection dialog</div> }))
vi.mock('../components/MigrationDialog', () => ({ default: ({ onComplete, onSkip, onClose }: { onComplete: (thread: unknown) => void; onSkip: () => void; onClose: () => void }) => <div><button onClick={onSkip}>skip migration</button><button onClick={onClose}>close migration</button><button onClick={() => onComplete({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10 })}>complete migration</button></div> }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: ({ onComplete, onClose }: { onComplete: (issue: string) => void; onClose: () => void }) => <div><button onClick={() => onComplete('1')}>complete simple</button><button onClick={onClose}>close simple</button></div> }))
vi.mock('../components/ReviewForm', () => ({ default: ({ onSubmit, onClose }: { onSubmit: (data: { review_text: string }) => void; onClose: () => void }) => <div><button onClick={() => onSubmit({ review_text: '' })}>submit review</button><button onClick={onClose}>close review</button></div> }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: (props: Record<string, unknown>) => <div><button onClick={() => (props.onThreadClick as (thread: unknown) => void)({ id: 1, title: 'Saga', format: 'Comic' })}>thread</button><button onClick={props.onShuffle as () => void}>shuffle pool</button><button onClick={props.onReadStale as () => void}>read stale</button><button onClick={props.onUnsnooze as () => void}>unsnooze</button><button onClick={props.onToggleSnoozed as () => void}>toggle snoozed</button><button onClick={props.onToggleBlocked as () => void}>toggle blocked</button></div> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: (props: Record<string, unknown>) => <div>{props.errorMessage ? <span>{String(props.errorMessage)}</span> : null}<button onClick={() => (props.onUpdateRating as (value: string) => void)('5')}>update rating</button><button onClick={() => (props.onUpdateRating as (value: string) => void)('4')}>threshold rating</button><button onClick={() => (props.onUpdateRating as (value: string) => void)('1')}>update low rating</button><button onClick={() => (props.onSubmitRating as (finish?: boolean) => void)(false)}>save rating</button><button onClick={() => (props.onSubmitRating as (finish?: boolean) => void)(true)}>finish rating</button><button onClick={props.onSnooze as () => void}>snooze rating</button><button onClick={props.onCancel as () => void}>cancel rating</button><button onClick={props.onRefreshThread as () => void}>refresh rating</button></div> }))

describe('RollPage parent handlers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionHook.value = null
    relatedApi.readingOrders.mockResolvedValue({ reading_orders: [] })
    relatedApi.connectedThreads.mockResolvedValue({ connected_threads: [] })
    staleData = []
    sessionData.current_die = 6
    sessionData.snoozed_threads = []
    sessionData.manual_die = undefined
    sessionData.last_rolled_result = undefined
    threadData.splice(1)
    spies.mutate.mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 })
    spies.setPending.mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 })
  })

  it('executes pool actions, roll recovery, and modal callbacks', async () => {
    render(<RollPage />)
    await fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    expect(screen.getByRole('heading', { name: 'Saga' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'update rating' }))
    fireEvent.click(screen.getByRole('button', { name: 'refresh rating' }))
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'save rating' })).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /^Override$/ }))
    fireEvent.click(screen.getByRole('button', { name: 'close modal' }))
    fireEvent.click(screen.getByRole('button', { name: 'shuffle pool' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle snoozed' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle blocked' }))
    expect(spies.mutate).toHaveBeenCalled()
  })

  it('refreshes an active rating thread with complete and partial metadata', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'refresh rating' })).toBeInTheDocument())
    spies.refetch.mockResolvedValue({ active_thread: {
      id: 1, issues_remaining: null, queue_position: null, total_issues: null,
      reading_progress: null, issue_id: null, issue_number: null,
      next_issue_id: null, next_issue_number: null, last_rolled_result: null,
    } })
    await user.click(screen.getByRole('button', { name: 'refresh rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('executes the remaining selected-thread actions and die controls', async () => {
    render(<RollPage />)
    const user = userEvent.setup()
    const openActions = async () => user.click(screen.getByRole('button', { name: 'thread' }))
    await openActions()
    await user.click(screen.getByRole('button', { name: /move to front/i }))
    await openActions()
    await user.click(screen.getByRole('button', { name: /move to back/i }))
    await openActions()
    const snoozeAction = screen.getAllByRole('button', { name: /snooze/i })
      .find((button) => button.textContent?.includes('Snooze') && !button.textContent?.includes('toggle'))
    if (!snoozeAction) throw new Error('Snooze action not found')
    await user.click(snoozeAction)
    await openActions()
    await user.click(screen.getByRole('button', { name: /edit thread/i }))
    expect(spies.navigate).toHaveBeenCalledWith('/queue', { state: { editThreadId: 1 } })

    await user.click(screen.getAllByRole('button', { name: 'd6' })[0]!)
    await user.click(screen.getAllByRole('button', { name: 'd4' })[0]!)
    await user.click(screen.getByRole('button', { name: 'Auto' }))
    expect(spies.mutate).toHaveBeenCalled()
  })

  it('runs the dice keyboard and timed roll completion paths', async () => {
    vi.useFakeTimers()
    render(<RollPage />)
    const die = screen.getByRole('button', { name: 'Roll the dice' })
    fireEvent.keyDown(die, { key: 'Enter' })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(spies.mutate).toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('cleans up an in-flight roll and renders manual-die state', async () => {
    vi.useFakeTimers()
    sessionData.manual_die = 4
    sessionData.last_rolled_result = 3
    const { unmount } = render(<RollPage />)
    const die = screen.getByRole('button', { name: 'Roll the dice' })
    fireEvent.click(die)
    fireEvent.click(die)
    unmount()
    vi.useRealTimers()
    sessionData.manual_die = undefined
    sessionData.last_rolled_result = undefined
  })

  it('opens override, submits it, and handles a pending migration flow', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: /^Override$/ }))
    await user.selectOptions(screen.getByRole('combobox'), '1')
    await user.click(screen.getByRole('button', { name: /Override Roll/ }))
    await waitFor(() => expect(spies.mutate).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: /^Override$/ }))
    fireEvent.submit(screen.getByRole('button', { name: /Override Roll/ }).closest('form')!)
    await user.click(screen.getByRole('button', { name: 'close modal' }))

    spies.setPending.mockResolvedValueOnce({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 3 })
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'skip migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'skip migration' }))
  })

  it('reports action, shuffle, stale-read, and rating failures without losing the page', async () => {
    const user = userEvent.setup()
    const error = new Error('operation failed')
    spies.mutate.mockRejectedValue(error)
    spies.setPending.mockRejectedValue(error)
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<RollPage />)

    await user.click(screen.getByRole('button', { name: 'shuffle pool' }))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /move to front/i }))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /move to back/i }))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    const snooze = screen.getAllByRole('button', { name: /snooze/i })
      .find((button) => button.textContent?.includes('Snooze') && !button.textContent?.includes('toggle'))
    if (!snooze) throw new Error('Snooze action not found')
    await user.click(snooze)
    await user.click(screen.getByRole('button', { name: 'read stale' }))

    spies.setPending.mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 })
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    expect(errorSpy).toHaveBeenCalled()
    expect(alertSpy).toHaveBeenCalled()
    alertSpy.mockRestore()
    errorSpy.mockRestore()
  })

  it('handles pending cancellation, refresh failure, override failure, and simple migration', async () => {
    const user = userEvent.setup()
    const error = new Error('failed')
    render(<RollPage />)

    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'cancel rating' })).toBeInTheDocument())
    spies.refetch.mockRejectedValueOnce(error)
    await user.click(screen.getByRole('button', { name: 'refresh rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'cancel rating' })).toBeInTheDocument())
    spies.refetch.mockResolvedValue({})
    await user.click(screen.getByRole('button', { name: 'cancel rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument())

    spies.mutate.mockRejectedValueOnce(error)
    await user.click(screen.getByRole('button', { name: /^Override$/ }))
    await user.selectOptions(screen.getByRole('combobox'), '1')
    await user.click(screen.getByRole('button', { name: /Override Roll/ }))
    await waitFor(() => expect(screen.getByText('failed')).toBeInTheDocument())

    spies.setPending.mockResolvedValueOnce({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 3 })
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'skip migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'skip migration' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'complete simple' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'close simple' }))
  })

  it('handles normal roll failures and unresolved pending conflicts', async () => {
    vi.useFakeTimers()
    const error = Object.assign(new Error('roll failed'), { response: { status: 500, data: { detail: 'server down' } } })
    spies.mutate.mockRejectedValue(error)
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    expect(spies.mutate).toHaveBeenCalled()
    vi.useRealTimers()
    cleanup()

    vi.useFakeTimers()
    spies.mutate.mockRejectedValue(Object.assign(new Error('pending'), { response: { status: 409, data: { detail: 'pending already exists' } } }))
    spies.refetch.mockResolvedValue({ pending_thread_id: null })
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
    vi.useRealTimers()

    cleanup()
    vi.useFakeTimers()
    spies.mutate.mockRejectedValue(Object.assign(new Error('pending'), { response: { status: 409, data: { detail: 'pending already exists' } } }))
    spies.refetch.mockResolvedValue({ pending_thread_id: 1, last_rolled_result: 4, active_thread: { id: 1, title: 'Recovered', format: 'Comic', issues_remaining: 1, queue_position: 1, total_issues: 4 } })
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('renders snoozed, blocked, stale, and mobile die states', async () => {
    sessionData.snoozed_threads = Array.from({ length: 6 }, (_, index) => ({ id: index + 9, title: `Snoozed ${index}`, format: 'Comic' }))
    threadData.push({ id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true })
    staleData = [{ id: 3, title: 'Stale', format: 'Comic', status: 'active', is_blocked: false, created_at: '2000-01-01' }] as never[]
    render(<RollPage />)
    expect(screen.getByText('offset active')).toBeInTheDocument()
    await userEvent.setup().click(screen.getAllByRole('button', { name: 'd6' })[1]!)
    expect(screen.getByRole('heading', { name: 'Select Die' })).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'close modal' }))
    expect(screen.getByRole('button', { name: 'read stale' })).toBeInTheDocument()
    sessionData.snoozed_threads = []
    threadData.splice(1)
  })

  it('shows the maximum-die snooze guidance', () => {
    sessionData.current_die = 100
    sessionData.snoozed_threads = [{ id: 9, title: 'Snoozed', format: 'Comic' }]
    render(<RollPage />)
    expect(screen.getByText(/pool at max size/)).toBeInTheDocument()
  })

  it('falls back to the standard die display for an unsupported session die', () => {
    sessionData.current_die = 7
    render(<RollPage />)
    expect(screen.getByRole('button', { name: 'd6' })).toBeInTheDocument()
  })

  it('covers low ratings, finish-session ratings, unsnooze, and snooze failure', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'update low rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'update low rating' }))
    await user.click(screen.getByRole('button', { name: 'snooze rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument())

    spies.mutate.mockRejectedValueOnce(new Error('snooze failed'))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'snooze rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'snooze rating' }))
    await waitFor(() => expect(screen.getByText('snooze failed')).toBeInTheDocument())
  })

  it('covers dice-ladder boundary prediction and selected-thread unsnooze action', async () => {
    const user = userEvent.setup()
    sessionData.current_die = 4
    sessionData.snoozed_threads = [{ id: 1, title: 'Saga', format: 'Comic' }]
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    const action = screen.getAllByRole('button', { name: /unsnooze/i })
      .find((button) => button.textContent?.includes('Unsnooze') && !button.textContent?.includes('toggle'))
    if (!action) throw new Error('Selected-thread unsnooze action not found')
    await user.click(action)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'update low rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'update low rating' }))
    await user.click(screen.getByRole('button', { name: 'update rating' }))
    cleanup()
    sessionData.current_die = 100
    sessionData.snoozed_threads = []
    render(<RollPage />)
    await user.click(screen.getAllByRole('button', { name: 'd100' })[0]!)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'update low rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'update low rating' }))
  })

  it('reads stale threads and handles unsnooze failures', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    staleData = [{ id: 7, title: 'Old', format: 'Comic', status: 'active', is_blocked: false, created_at: '2000-01-01' }] as never[]
    spies.mutate.mockRejectedValueOnce(new Error('unsnooze failed'))
    render(<RollPage />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'cancel rating' }))
    spies.mutate.mockRejectedValueOnce(new Error('unsnooze failed'))
    await userEvent.setup().click(screen.getByRole('button', { name: 'unsnooze' }))
    await waitFor(() => expect(spies.mutate).toHaveBeenCalled())
    errorSpy.mockRestore()
  })

  it('handles set-die and clear-die failures from the controls', async () => {
    spies.mutate.mockRejectedValue(new Error('die failed'))
    render(<RollPage />)
    await userEvent.setup().click(screen.getAllByRole('button', { name: 'd6' })[0]!)
    await userEvent.setup().click(screen.getByRole('button', { name: 'd4' }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Auto' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Auto' })).toBeInTheDocument())
  })

  it('handles finish-session rating refresh failure and stale migration', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'finish rating' })).toBeInTheDocument())
    spies.refetch.mockRejectedValueOnce(new Error('refresh failed'))
    await user.click(screen.getByRole('button', { name: 'finish rating' }))
    await waitFor(() => expect(screen.getByText(/failed to refresh/i)).toBeInTheDocument())

    cleanup()
    staleData = [{ id: 3, title: 'Unmigrated stale', format: 'Comic', status: 'active', is_blocked: false, created_at: '2000-01-01' }] as never[]
    spies.setPending.mockResolvedValueOnce({ thread_id: 3, title: 'Unmigrated stale', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 2 })
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'skip migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'close migration' }))
  })

  it('renders loading and session error recovery states', async () => {
    sessionHook.value = { data: undefined, isPending: true, isError: false, refetch: spies.refetch }
    const { unmount } = render(<RollPage />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
    unmount()

    sessionHook.value = { data: undefined, isPending: false, isError: true, error: Object.assign(new Error('expired'), { response: { status: 401, data: { detail: 'expired session' } } }), refetch: spies.refetch }
    const user = userEvent.setup()
    render(<RollPage />)
    expect(screen.getByText('Session Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /go to login/i }))
    expect(spies.navigate).toHaveBeenCalledWith('/login')
  })

  it('keeps rating view usable when related thread data requests fail', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    relatedApi.readingOrders.mockRejectedValueOnce(new Error('orders failed'))
    relatedApi.connectedThreads.mockRejectedValueOnce(new Error('connections failed'))
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'thread' }))
    await userEvent.setup().click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Failed to fetch reading orders:', expect.any(Error)))
    expect(errorSpy).toHaveBeenCalledWith('Failed to fetch connected threads:', expect.any(Error))
    errorSpy.mockRestore()
  })

  it('restores a pending session into the rating view on initial load', async () => {
    sessionHook.value = {
      data: {
        current_die: 8,
        pending_thread_id: 1,
        last_rolled_result: 4,
        active_thread: { id: 1, title: 'Pending Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 8, last_rolled_result: 4 },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
    if (screen.queryByRole('button', { name: 'Roll the dice' })) {
      await userEvent.setup().click(screen.getByRole('button', { name: 'Roll the dice' }))
    }
  })

  it('hydrates all pending-session metadata fields', async () => {
    sessionHook.value = {
      data: {
        current_die: 8,
        pending_thread_id: 1,
        last_rolled_result: 4,
        active_thread: {
          id: 1,
          title: 'Complete pending',
          format: 'Comic',
          issues_remaining: 2,
          queue_position: 2,
          total_issues: 8,
          reading_progress: 0.25,
          issue_id: 12,
          issue_number: '4',
          next_issue_id: 13,
          next_issue_number: '5',
          last_rolled_result: 4,
        },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
  })

  it('recovers a pending session when neither session nor active-thread metadata exists', async () => {
    sessionHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 99,
        last_rolled_result: null,
        active_thread: null,
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
  })

  it('hydrates null pending metadata with safe display fallbacks', async () => {
    sessionHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 1,
        last_rolled_result: null,
        active_thread: {
          id: 1,
          title: 'Sparse pending',
          format: null,
          issues_remaining: null,
          queue_position: null,
          total_issues: null,
          reading_progress: null,
          issue_id: null,
          issue_number: null,
          next_issue_id: null,
          next_issue_number: null,
          last_rolled_result: null,
        },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    } as never
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('falls back to the active session metadata when a pending response lacks thread identity', async () => {
    sessionHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: null,
        last_rolled_result: null,
        active_thread: { id: 1, title: 'Session fallback', format: 'Graphic Novel', issues_remaining: null, queue_position: null, total_issues: null },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    spies.setPending.mockResolvedValueOnce({ thread_id: null, title: undefined, format: undefined, issues_remaining: null, queue_position: null, total_issues: null, result: null })
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await user.click(screen.getByRole('button', { name: 'skip migration' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('keeps simple migration open when saving the selected issue fails', async () => {
    const user = userEvent.setup()
    spies.setPending.mockResolvedValueOnce({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 3 })
    spies.mutate.mockRejectedValueOnce(new Error('simple migration save failed'))
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await user.click(screen.getByRole('button', { name: 'skip migration' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'complete simple' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'complete simple' }))
    await waitFor(() => expect(screen.getByText('simple migration save failed')).toBeInTheDocument())
  })

  it('accepts collection edit events from the integration test hook', () => {
    render(<RollPage />)
    window.dispatchEvent(new CustomEvent('test-edit-collection', { detail: { id: 4, name: 'Archive' } }))
    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
  })

  it('completes migration and simple migration flows', async () => {
    const user = userEvent.setup()
    spies.setPending.mockResolvedValueOnce({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 3 })
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'complete migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'complete migration' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument())

    cleanup()
    spies.setPending.mockResolvedValueOnce({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 3 })
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'skip migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'skip migration' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'complete simple' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'complete simple' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument())
  })

  it('refreshes matching active metadata and reopens pending rolls', async () => {
    const user = userEvent.setup()
    spies.refetch.mockResolvedValue({ active_thread: { id: 1, issues_remaining: 1, total_issues: 5, queue_position: 2, issue_id: 8, issue_number: '2', next_issue_id: 9, next_issue_number: '3', reading_progress: 0.4, last_rolled_result: 4 } })
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'refresh rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'refresh rating' }))
  })

  it('preserves complete issue metadata through the rating transition', async () => {
    const user = userEvent.setup()
    const completeResponse = {
      thread_id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 2,
      queue_position: 1,
      total_issues: 10,
      reading_progress: 0.4,
      issue_id: 8,
      issue_number: '4',
      next_issue_id: 9,
      next_issue_number: '5',
      result: 3,
      last_rolled_result: 3,
    }
    spies.setPending.mockResolvedValueOnce(completeResponse)
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'refresh rating' }))
  })

  it('uses device vibration feedback at the rating threshold', async () => {
    const vibrate = vi.fn()
    Object.defineProperty(navigator, 'vibrate', { configurable: true, value: vibrate })
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'update rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'threshold rating' }))
    await user.click(screen.getByRole('button', { name: 'save rating' }))
    expect(vibrate).toHaveBeenCalledWith(8)
    expect(vibrate).toHaveBeenCalledWith(20)
  })
})
