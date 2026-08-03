import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

const spies = vi.hoisted(() => ({
  navigate: vi.fn(), refetch: vi.fn().mockResolvedValue({}),
  setDie: vi.fn().mockResolvedValue({}), clearDie: vi.fn().mockResolvedValue({}),
  roll: vi.fn().mockResolvedValue({}), dismissPending: vi.fn().mockResolvedValue({}),
  override: vi.fn().mockResolvedValue({}), snooze: vi.fn().mockResolvedValue({}),
  unsnooze: vi.fn().mockResolvedValue({}), moveFront: vi.fn().mockResolvedValue({}),
  moveBack: vi.fn().mockResolvedValue({}), shuffle: vi.fn().mockResolvedValue({}),
  rate: vi.fn().mockResolvedValue({}),
  setPending: vi.fn().mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 }),
}))
const sessionHook = vi.hoisted(() => ({ value: null as unknown }))
const bootstrapHook = vi.hoisted(() => ({ value: null as unknown }))
const relatedApi = vi.hoisted(() => ({ readingOrders: vi.fn(), connectedThreads: vi.fn(), blockingInfo: vi.fn() }))
const sessionData: { current_die: number; snoozed_threads: Array<{ id: number; title: string; format: string }>; manual_die?: number; last_rolled_result?: number | null } = { current_die: 6, snoozed_threads: [] }
const bootstrapData: { current_die: number; snoozed_threads: Array<{ id: number; title: string; format: string }>; roll_pool: Array<{ id: number; title: string; format: string }>; manual_die?: number | null; last_rolled_result?: number | null; pending_thread_id?: number | null; active_thread?: unknown; blocked_count: number; blocked_threads: Array<{ id: number; title: string; format: string }>; stale_thread_count: number; stale_thread: { id: number; title: string; format: string; last_activity_at?: string } | null; snoozed_count: number } = { current_die: 6, snoozed_threads: [], roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }], manual_die: null, last_rolled_result: null, pending_thread_id: null, active_thread: null, blocked_count: 0, blocked_threads: [], stale_thread_count: 0, stale_thread: null, snoozed_count: 0 }
const threadData: Array<{ id: number; title: string; format: string; status: string; is_blocked?: boolean }> = [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }]
let staleData: never[] = []
let threadsValue: unknown = threadData

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({ activeCollectionId: null, collections: [] }) }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn((restore: () => void) => restore()),
    clearRestoreAction: vi.fn(),
  }),
}))
vi.mock('../hooks/useSession', () => ({ useSession: () => sessionHook.value ?? ({ data: sessionData, refetch: spies.refetch }) }))
vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: () => bootstrapHook.value ?? ({ data: bootstrapData, refetch: spies.refetch, isPending: false, isError: false, error: null }) }))
vi.mock('../hooks/useThread', () => ({ useThreads: () => ({ data: threadsValue, refetch: spies.refetch }), useStaleThreads: () => ({ data: staleData, refetch: spies.refetch }) }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: spies.setDie, isPending: false }), useClearManualDie: () => ({ mutate: spies.clearDie, isPending: false }),
  useRoll: () => ({ mutate: spies.roll, isPending: false }), useDismissPending: () => ({ mutate: spies.dismissPending, isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.override, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: () => ({ mutate: spies.snooze, isPending: false }), useUnsnooze: () => ({ mutate: spies.unsnooze, isPending: false }) }))
vi.mock('../hooks/useQueue', () => ({ useMoveToFront: () => ({ mutate: spies.moveFront, isPending: false }), useMoveToBack: () => ({ mutate: spies.moveBack, isPending: false }), useShuffleQueue: () => ({ mutate: spies.shuffle, isPending: false }) }))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: spies.rate, isPending: false }) }))
vi.mock('../services/api', () => ({ threadsApi: { setPending: spies.setPending, list: vi.fn().mockResolvedValue({ threads: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }], next_page_token: null }) }, dependenciesApi: { getConnectedThreads: relatedApi.connectedThreads, getBlockingInfo: relatedApi.blockingInfo } }))
vi.mock('../services/api-reading-orders', () => ({ readingOrdersApi: { getForThread: relatedApi.readingOrders } }))
vi.mock('../components/LazyDice3D', () => ({
  default: ({ onRollComplete }: { onRollComplete?: () => void }) => (
    <div data-testid="dice"><button type="button" onClick={onRollComplete}>complete dice</button></div>
  ),
}))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/CollectionDialog', () => ({ default: ({ collection }: { collection: { name?: string } | null }) => <div data-testid="collection-dialog">collection dialog {collection?.name ?? 'new'}</div> }))
vi.mock('../components/MigrationDialog', () => ({ default: ({ onComplete, onSkip, onClose }: { onComplete: (thread: unknown) => void; onSkip: () => void; onClose: () => void }) => <div><button onClick={onSkip}>skip migration</button><button onClick={onClose}>close migration</button><button onClick={() => onComplete({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10 })}>complete migration</button></div> }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: ({ onComplete, onClose }: { onComplete: (issue: string) => void; onClose: () => void }) => <div><button onClick={() => onComplete('1')}>complete simple</button><button onClick={onClose}>close simple</button></div> }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: (props: Record<string, unknown>) => <div><button onClick={() => (props.onThreadClick as (thread: unknown) => void)({ id: 1, title: 'Saga', format: 'Comic' })}>thread</button><button onClick={props.onShuffle as () => void}>shuffle pool</button><button onClick={props.onReadStale as () => void}>read stale</button><button onClick={props.onUnsnooze as () => void}>unsnooze</button><button onClick={props.onToggleSnoozed as () => void}>toggle snoozed</button><button onClick={props.onToggleBlocked as () => void}>toggle blocked</button><span>{JSON.stringify(props.blockingReasonMap)}</span></div> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: (props: Record<string, unknown>) => {
  const thread = props.activeRatingThread as { title?: string; issue_number?: string | null } | null
  return <div>
    <span data-testid="rating-thread-metadata">{thread?.title ?? 'missing'}:{thread?.issue_number ?? 'none'}</span>
    {props.errorMessage ? <span>{String(props.errorMessage)}</span> : null}
    <button onClick={() => (props.onUpdateRating as (value: string) => void)('5')}>update rating</button><button onClick={() => (props.onUpdateRating as (value: string) => void)('4')}>threshold rating</button><button onClick={() => (props.onUpdateRating as (value: string) => void)('1')}>update low rating</button><button onClick={() => (props.onSubmitRating as (finish?: boolean) => void)(false)}>save rating</button><button onClick={() => (props.onSubmitRating as (finish?: boolean) => void)(true)}>finish rating</button><button onClick={props.onSnooze as () => void}>snooze rating</button><button onClick={props.onCancel as () => void}>cancel rating</button><button onClick={props.onRefreshThread as () => void}>refresh rating</button>
  </div>
} }))

describe('RollPage parent handlers', () => {
  afterEach(() => vi.useRealTimers())

  beforeEach(() => {
    vi.clearAllMocks()
    sessionHook.value = null
    bootstrapHook.value = null
    relatedApi.readingOrders.mockResolvedValue({ reading_orders: [] })
    relatedApi.connectedThreads.mockResolvedValue({ connected_threads: [] })
    relatedApi.blockingInfo.mockResolvedValue({ blocking_reasons: ['Read the prerequisite first'] })
    staleData = []
    threadsValue = threadData
    sessionData.current_die = 6
    sessionData.snoozed_threads = []
    sessionData.manual_die = undefined
    sessionData.last_rolled_result = undefined
    threadData.splice(1)
    bootstrapData.current_die = sessionData.current_die
    bootstrapData.manual_die = sessionData.manual_die ?? null
    bootstrapData.pending_thread_id = null
    bootstrapData.last_rolled_result = sessionData.last_rolled_result ?? null
    bootstrapData.active_thread = null
    bootstrapData.roll_pool = (threadsValue ? (threadsValue as any[]).filter((t: any) => t.status === 'active' && !t.is_blocked).map((t: any) => ({ id: t.id, title: t.title, format: t.format })) : threadData.filter((t: any) => t.status === 'active' && !t.is_blocked).map((t: any) => ({ id: t.id, title: t.title, format: t.format })))
    bootstrapData.snoozed_threads = sessionData.snoozed_threads
    bootstrapData.snoozed_count = 0
    bootstrapData.blocked_count = 0
    bootstrapData.blocked_threads = []
    bootstrapData.stale_thread_count = 0
    bootstrapData.stale_thread = null
    for (const mutation of [spies.setDie, spies.clearDie, spies.roll, spies.dismissPending, spies.override, spies.snooze, spies.unsnooze, spies.moveFront, spies.moveBack, spies.shuffle, spies.rate]) mutation.mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 })
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
    expect(spies.shuffle).toHaveBeenCalled()
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
    expect(spies.setDie).toHaveBeenCalled()
  })

  it('runs the dice keyboard and timed roll completion paths', async () => {
    vi.useFakeTimers()
    render(<RollPage />)
    const die = screen.getByRole('button', { name: 'Roll the dice' })
    fireEvent.keyDown(die, { key: 'Enter' })
    fireEvent.keyDown(die, { key: 'Tab' })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(spies.roll).toHaveBeenCalled()
    fireEvent.keyDown(die, { key: ' ' })
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
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    unmount()
    vi.useRealTimers()
    sessionData.manual_die = undefined
    sessionData.last_rolled_result = undefined
  })

  it('opens override, submits it, and handles a pending migration flow', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: /^Override$/ }))
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '1')
    await user.click(screen.getByRole('button', { name: /Override Roll/ }))
    await waitFor(() => expect(spies.override).toHaveBeenCalled())

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
    spies.shuffle.mockRejectedValue(error)
    spies.moveFront.mockRejectedValue(error)
    spies.moveBack.mockRejectedValue(error)
    spies.snooze.mockRejectedValue(error)
    spies.rate.mockRejectedValue(error)
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

    spies.override.mockRejectedValueOnce(error)
    await user.click(screen.getByRole('button', { name: /^Override$/ }))
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '1')
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
    spies.roll.mockRejectedValue(error)
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    expect(spies.roll).toHaveBeenCalled()
    vi.useRealTimers()
    cleanup()

    vi.useFakeTimers()
    spies.roll.mockRejectedValue(Object.assign(new Error('pending'), { response: { status: 409, data: { detail: 'pending already exists' } } }))
    spies.refetch.mockResolvedValue({ pending_thread_id: null })
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
    vi.useRealTimers()

    cleanup()
    vi.useFakeTimers()
    spies.roll.mockRejectedValue(Object.assign(new Error('pending'), { response: { status: 409, data: { detail: 'pending already exists' } } }))
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
    bootstrapData.snoozed_threads = sessionData.snoozed_threads
    bootstrapData.snoozed_count = 6
    threadData.push({ id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true })
    bootstrapData.blocked_threads = [{ id: 2, title: 'Blocked', format: 'Comic' }]
    bootstrapData.blocked_count = 1
    staleData = [{ id: 3, title: 'Stale', format: 'Comic', status: 'active', is_blocked: false, created_at: '2000-01-01' }] as never[]
    bootstrapData.stale_thread = { id: 3, title: 'Stale', format: 'Comic', last_activity_at: '2000-01-01T00:00:00Z' }
    bootstrapData.stale_thread_count = 1
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
    bootstrapData.current_die = 100
    sessionData.snoozed_threads = [{ id: 9, title: 'Snoozed', format: 'Comic' }]
    bootstrapData.snoozed_threads = [{ id: 9, title: 'Snoozed', format: 'Comic' }]
    bootstrapData.snoozed_count = 1
    render(<RollPage />)
    expect(screen.getByText(/pool at max size/)).toBeInTheDocument()
  })

  it('falls back to the standard die display for an unsupported session die', () => {
    sessionData.current_die = 7
    render(<RollPage />)
    expect(screen.getAllByRole('button', { name: 'd6' })[0]).toBeInTheDocument()
  })

  it('separates completed, blocked, and snoozed threads from the active pool', () => {
    sessionData.snoozed_threads = [{ id: 1, title: 'Saga', format: 'Comic' }]
    bootstrapData.snoozed_threads = [{ id: 1, title: 'Saga', format: 'Comic' }]
    bootstrapData.snoozed_count = 1
    threadData.push(
      { id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true },
      { id: 3, title: 'Completed', format: 'Comic', status: 'completed', is_blocked: false },
    )
    bootstrapData.roll_pool = [{ id: 1, title: 'Saga', format: 'Comic' }]
    bootstrapData.blocked_threads = [{ id: 2, title: 'Blocked', format: 'Comic' }]
    bootstrapData.blocked_count = 1
    render(<RollPage />)
    expect(screen.getByRole('button', { name: 'toggle snoozed' })).toBeInTheDocument()
    threadData.splice(1)
    sessionData.snoozed_threads = []
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

    spies.snooze.mockRejectedValueOnce(new Error('snooze failed'))
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'snooze rating' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'snooze rating' }))
    await waitFor(() => expect(screen.getByText('snooze failed')).toBeInTheDocument())
  })

  it('covers dice-ladder boundary prediction and selected-thread unsnooze action', async () => {
    const user = userEvent.setup()
    sessionData.current_die = 4
    bootstrapData.current_die = 4
    sessionData.snoozed_threads = [{ id: 1, title: 'Saga', format: 'Comic' }]
    bootstrapData.snoozed_threads = [{ id: 1, title: 'Saga', format: 'Comic' }]
    bootstrapData.snoozed_count = 1
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
    bootstrapData.current_die = 100
    sessionData.snoozed_threads = []
    bootstrapData.snoozed_threads = []
    bootstrapData.snoozed_count = 0
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
    bootstrapData.stale_thread = { id: 7, title: 'Old', format: 'Comic', last_activity_at: '2000-01-01T00:00:00Z' }
    bootstrapData.stale_thread_count = 1
    spies.unsnooze.mockRejectedValueOnce(new Error('unsnooze failed'))
    render(<RollPage />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'cancel rating' }))
    spies.unsnooze.mockRejectedValueOnce(new Error('unsnooze failed'))
    await userEvent.setup().click(screen.getByRole('button', { name: 'unsnooze' }))
    await waitFor(() => expect(spies.unsnooze).toHaveBeenCalled())
    errorSpy.mockRestore()
  })

  it('ignores blocked and recently active stale candidates', async () => {
    staleData = [
      { id: 8, title: 'Blocked old', format: 'Comic', status: 'active', is_blocked: true, created_at: '2000-01-01' },
      { id: 9, title: 'Recent', format: 'Comic', status: 'active', is_blocked: false, last_activity_at: new Date().toISOString(), created_at: '2000-01-01' },
    ] as never[]
    bootstrapData.stale_thread = null
    bootstrapData.stale_thread_count = 0
    threadData.push({ id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true })
    relatedApi.blockingInfo.mockResolvedValueOnce({})
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'read stale' }))
    expect(spies.setPending).not.toHaveBeenCalled()
  })

  it('renders safely while the thread list is unavailable', () => {
    threadsValue = undefined
    render(<RollPage />)
    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
  })

  it('reports an invalid rating-thread response without entering rating mode', async () => {
    spies.setPending.mockResolvedValueOnce({ thread_id: null, title: '', format: 'Comic', issues_remaining: 1, queue_position: 1, total_issues: 2, result: null })
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'thread' }))
    await userEvent.setup().click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'save rating' })).not.toBeInTheDocument())
  })

  it('hydrates a pending id from the queue when session metadata belongs elsewhere', async () => {
    sessionHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 1,
        last_rolled_result: null,
        active_thread: { id: 2, title: 'Other', format: 'Comic', issues_remaining: 1, queue_position: 2, total_issues: 2 },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    bootstrapData.pending_thread_id = 1
    bootstrapData.last_rolled_result = null
    bootstrapData.active_thread = { id: 2, title: 'Other', format: 'Comic', issues_remaining: 1, queue_position: 2, total_issues: 2, last_rolled_result: null }
    bootstrapData.roll_pool = [{ id: 1, title: 'Saga', format: 'Comic' }]
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('rating-thread-metadata')).toHaveTextContent('Saga'))
  })

  it('uses stale roll-result fallback without loading hidden blocking reasons', async () => {
    staleData = [{ id: 7, title: 'Old', format: 'Comic', status: 'active', is_blocked: false, created_at: '2000-01-01' }] as never[]
    threadData.push({ id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true })
    bootstrapData.stale_thread = { id: 7, title: 'Old', format: 'Comic', last_activity_at: '2000-01-01T00:00:00Z' }
    bootstrapData.stale_thread_count = 1
    spies.setPending.mockResolvedValueOnce({ thread_id: 7, title: 'Old', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: null, last_rolled_result: 5 })
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'read stale' })).toBeInTheDocument())
    expect(relatedApi.blockingInfo).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    expect(spies.setPending).toHaveBeenCalledWith(7)
  })

  it('loads blocked reasons only when the blocked pool is expanded', async () => {
    threadData.push({ id: 2, title: 'Blocked', format: 'Comic', status: 'active', is_blocked: true })
    bootstrapData.blocked_threads = [{ id: 2, title: 'Blocked', format: 'Comic' }]
    bootstrapData.blocked_count = 1
    relatedApi.blockingInfo.mockReset().mockResolvedValue({ blocking_reasons: ['Read the prerequisite first'] })
    render(<RollPage />)
    expect(relatedApi.blockingInfo).not.toHaveBeenCalled()

    await userEvent.setup().click(screen.getByRole('button', { name: 'toggle blocked' }))

    await waitFor(() => expect(relatedApi.blockingInfo).toHaveBeenCalledWith(2))
    expect(screen.getByText(/Read the prerequisite first/)).toBeInTheDocument()
  })

  it('uses the safe die fallback when a pending session has an invalid die', async () => {
    sessionHook.value = {
      data: {
        current_die: 0,
        pending_thread_id: 1,
        last_rolled_result: null,
        active_thread: { id: 1, title: 'Pending Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 8 },
        snoozed_threads: [],
      },
      refetch: spies.refetch,
    }
    bootstrapData.current_die = 0
    bootstrapData.pending_thread_id = 1
    bootstrapData.last_rolled_result = null
    bootstrapData.active_thread = { id: 1, title: 'Pending Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 8, last_rolled_result: null }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('handles set-die and clear-die failures from the controls', async () => {
    spies.setDie.mockRejectedValue(new Error('die failed'))
    spies.clearDie.mockRejectedValue(new Error('die failed'))
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
    bootstrapData.stale_thread = { id: 3, title: 'Unmigrated stale', format: 'Comic', last_activity_at: '2000-01-01T00:00:00Z' }
    bootstrapData.stale_thread_count = 1
    spies.setPending.mockResolvedValueOnce({ thread_id: 3, title: 'Unmigrated stale', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: null, result: 2 })
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'skip migration' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'close migration' }))
  })

  it('renders loading and session error recovery states', async () => {
    sessionHook.value = { data: undefined, isPending: true, isError: false, refetch: spies.refetch }
    bootstrapHook.value = { data: undefined, isPending: true, isError: false, refetch: spies.refetch, error: null }
    const { unmount } = render(<RollPage />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
    unmount()

    sessionHook.value = { data: undefined, isPending: false, isError: true, error: Object.assign(new Error('expired'), { response: { status: 401, data: { detail: 'expired session' } } }), refetch: spies.refetch }
    bootstrapHook.value = { data: undefined, isPending: false, isError: true, error: Object.assign(new Error('expired'), { response: { status: 401, data: { detail: 'expired session' } } }), refetch: spies.refetch }
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
    bootstrapData.current_die = 8
    bootstrapData.pending_thread_id = 1
    bootstrapData.last_rolled_result = 4
    bootstrapData.active_thread = { id: 1, title: 'Pending Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 8, last_rolled_result: 4 }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
    if (screen.queryByRole('button', { name: 'Roll the dice' })) {
      await userEvent.setup().click(screen.getByRole('button', { name: 'Roll the dice' }))
    }
  })

  it('hydrates all pending-session metadata fields', async () => {
    bootstrapHook.value = {
      data: {
        current_die: 8,
        pending_thread_id: 1,
        last_rolled_result: 4,
        manual_die: null,
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
        snoozed_count: 0,
        roll_pool: [{ id: 1, title: 'Complete pending', format: 'Comic' }],
        blocked_count: 0,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    expect(screen.getByTestId('rating-thread-metadata')).toHaveTextContent('Complete pending:4')
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
  })

  it('recovers a pending session when neither session nor active-thread metadata exists', async () => {
    bootstrapHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 99,
        last_rolled_result: null,
        manual_die: null,
        active_thread: null,
        snoozed_threads: [],
        snoozed_count: 0,
        roll_pool: [],
        blocked_count: 0,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'save rating' }))
  })

  it('hydrates null pending metadata with safe display fallbacks', async () => {
    bootstrapHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 1,
        last_rolled_result: null,
        manual_die: null,
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
        snoozed_count: 0,
        roll_pool: [{ id: 1, title: 'Sparse pending', format: '' }],
        blocked_count: 0,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    } as never
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('falls back to the active session metadata when a pending response lacks thread identity', async () => {
    bootstrapData.active_thread = { id: 1, title: 'Session fallback', format: 'Graphic Novel', issues_remaining: null, queue_position: null, total_issues: null, last_rolled_result: null }
    bootstrapData.roll_pool = [{ id: 1, title: 'Session fallback', format: 'Graphic Novel' }]
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
    spies.rate.mockRejectedValueOnce(new Error('simple migration save failed'))
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

  it('reports pool, stale-read, and action failures without leaving the page stuck', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    spies.shuffle.mockRejectedValue(new Error('pool failed'))
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'shuffle pool' }))
    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith('Failed to shuffle pool: pool failed'))

    cleanup()
    bootstrapData.stale_thread = { id: 7, title: 'Old', format: 'Comic', last_activity_at: '2000-01-01' } as never
    bootstrapData.stale_thread_count = 1
    spies.setPending.mockRejectedValueOnce(new Error('stale failed'))
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'read stale' }))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Failed to set pending thread:', expect.any(Error)))

    cleanup()
    spies.setPending.mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10 })
    spies.moveFront.mockRejectedValue(new Error('move failed'))
    render(<RollPage />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'thread' }))
    await userEvent.setup().click(screen.getByRole('button', { name: /move to front/i }))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Action failed:', expect.any(Error)))
    alertSpy.mockRestore()
    errorSpy.mockRestore()
    bootstrapData.stale_thread = null
    bootstrapData.stale_thread_count = 0
  })

  it('handles sparse roll metadata, recent stale activity, and pending-thread fallback selection', async () => {
    const user = userEvent.setup()
    sessionData.current_die = 0
    sessionData.last_rolled_result = null
    staleData = [{
      id: 8, title: 'Recently active', format: 'Comic', status: 'active', is_blocked: false,
      created_at: '2026-07-18T00:00:00Z', last_activity_at: '2026-07-18T00:00:00Z',
    }] as never[]
    spies.setPending.mockResolvedValueOnce({
      thread_id: 1, title: 'Sparse', format: 'Comic', issues_remaining: 1,
      queue_position: 1, total_issues: 2, result: undefined, last_rolled_result: 4,
    })
    render(<RollPage />)
    expect(screen.getAllByRole('button', { name: 'd6' })[0]).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())

    cleanup()
    bootstrapHook.value = {
      data: { current_die: 6, pending_thread_id: 1, last_rolled_result: null, manual_die: null, active_thread: null, snoozed_threads: [], snoozed_count: 0, roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }], blocked_count: 0, blocked_threads: [], stale_thread_count: 0, stale_thread: null },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    bootstrapHook.value = null
    sessionData.current_die = 6
    bootstrapData.stale_thread = null
    bootstrapData.stale_thread_count = 0
  })

  it('opens a hydrated pending session and recovers pending roll conflicts', async () => {
    bootstrapHook.value = {
      data: {
        current_die: 6,
        pending_thread_id: 1,
        last_rolled_result: 4,
        manual_die: null,
        active_thread: {
          id: 1, title: 'Pending Saga', format: 'Comic', issues_remaining: 2,
          queue_position: 1, total_issues: 8, issue_id: 10, issue_number: '4',
          next_issue_id: 11, next_issue_number: '5', reading_progress: 0.5,
          last_rolled_result: 4,
        },
        snoozed_threads: [],
        snoozed_count: 0,
        roll_pool: [{ id: 1, title: 'Pending Saga', format: 'Comic' }],
        blocked_count: 0,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    expect(screen.getByTestId('rating-thread-metadata')).toHaveTextContent('Pending Saga:4')
    cleanup()
    bootstrapHook.value = null
    render(<RollPage />)
    spies.refetch.mockResolvedValueOnce({ pending_thread_id: 1, last_rolled_result: 3, active_thread: { id: 1, title: 'Recovered', format: 'Comic', issues_remaining: 1, queue_position: 1, total_issues: 4 } })
    spies.roll.mockRejectedValueOnce(Object.assign(new Error('pending'), { response: { status: 409, data: { detail: 'pending' } } }))
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Roll the dice' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
    vi.useRealTimers()
  })

  it('handles related-thread request failures while entering rating', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    relatedApi.readingOrders.mockRejectedValueOnce(new Error('orders failed'))
    relatedApi.connectedThreads.mockRejectedValueOnce(new Error('connected failed'))
    const user = userEvent.setup()
    render(<RollPage />)
    await user.click(screen.getByRole('button', { name: 'thread' }))
    await user.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    expect(errorSpy).toHaveBeenCalledWith('Failed to fetch reading orders:', expect.any(Error))
    expect(errorSpy).toHaveBeenCalledWith('Failed to fetch connected threads:', expect.any(Error))
    errorSpy.mockRestore()
  })
})
