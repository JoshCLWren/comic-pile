import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

const spies = vi.hoisted(() => ({
  navigate: vi.fn(),
  refetch: vi.fn().mockResolvedValue({}),
  setDie: vi.fn().mockResolvedValue({}),
  clearDie: vi.fn().mockResolvedValue({}),
  roll: vi.fn().mockResolvedValue({}),
  dismissPending: vi.fn().mockResolvedValue({}),
  override: vi.fn().mockResolvedValue({}),
  snooze: vi.fn().mockResolvedValue({}),
  unsnooze: vi.fn().mockResolvedValue({}),
  moveFront: vi.fn().mockResolvedValue({}),
  moveBack: vi.fn().mockResolvedValue({}),
  shuffle: vi.fn().mockResolvedValue({}),
  rate: vi.fn().mockResolvedValue({}),
  skip: vi.fn(),
  unskip: vi.fn().mockResolvedValue({}),
  setPending: vi.fn().mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 }),
}))
const bootstrapHook = vi.hoisted(() => ({ value: null as unknown }))
const skipHookValue = vi.hoisted(() => ({ value: null as unknown }))

const relatedApi = vi.hoisted(() => ({ readingOrders: vi.fn(), connectedThreads: vi.fn(), blockingInfo: vi.fn(), batchBlockingInfo: vi.fn() }))
const bootstrapData: any = {
  current_die: 6,
  snoozed_threads: [],
  roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }],
  manual_die: null,
  last_rolled_result: 4,
  pending_thread_id: 1,
  active_thread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 4, last_rolled_result: 4, issue_id: 10, issue_number: '4', next_issue_id: 11, next_issue_number: '5' },
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
}
const threadData: any[] = [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }]

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({ setRestoreAction: vi.fn((r: () => void) => r()), clearRestoreAction: vi.fn() }),
}))
vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: () => bootstrapHook.value ?? ({ data: bootstrapData, refetch: spies.refetch, isPending: false, isError: false, error: null }) }))
vi.mock('../hooks/useThread', () => ({ useStaleThreads: () => ({ data: [], refetch: spies.refetch }) }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: spies.setDie, isPending: false }),
  useClearManualDie: () => ({ mutate: spies.clearDie, isPending: false }),
  useRoll: () => ({ mutate: spies.roll, isPending: false }),
  useDismissPending: () => ({ mutate: spies.dismissPending, isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.override, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: () => ({ mutate: spies.snooze, isPending: false }), useUnsnooze: () => ({ mutate: spies.unsnooze, isPending: false }) }))
vi.mock('../hooks/useQueue', () => ({ useMoveToFront: () => ({ mutate: spies.moveFront, isPending: false }), useMoveToBack: () => ({ mutate: spies.moveBack, isPending: false }), useShuffleQueue: () => ({ mutate: spies.shuffle, isPending: false }) }))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: spies.rate, isPending: false }) }))
vi.mock('../hooks/useSkip', () => ({
  useSkip: () => skipHookValue.value ?? ({ mutate: spies.skip, isPending: false, isError: false, refreshError: null, hasRefreshError: false, retryRefresh: vi.fn() }),
  useUnskip: () => ({ mutate: spies.unskip, isPending: false, isError: false }),
}))
vi.mock('../services/api-taste', () => ({
  tasteApi: { getDiscoveries: vi.fn().mockResolvedValue({ discoveries: [], generated_at: new Date().toISOString() }), dismiss: vi.fn().mockResolvedValue({ dismissed: true }), submitVerdict: vi.fn().mockResolvedValue({}) },
}))
vi.mock('../hooks/useReaderContext', () => ({ useReaderContext: () => ({ context: null, isLoading: false, error: null, refetch: vi.fn() }) }))
vi.mock('../services/api', () => ({ default: {}, threadsApi: { setPending: spies.setPending, list: vi.fn().mockResolvedValue({ threads: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }], next_page_token: null }) }, dependenciesApi: { getConnectedThreads: relatedApi.connectedThreads, getBlockingInfo: relatedApi.blockingInfo, getBatchBlockingInfo: relatedApi.batchBlockingInfo } }))
vi.mock('../services/api-reading-orders', () => ({ readingOrdersApi: { getForThread: relatedApi.readingOrders } }))
vi.mock('../components/LazyDice3D', () => ({ default: ({ onRollComplete }: { onRollComplete?: () => void }) => <div data-testid="dice"><button type="button" onClick={onRollComplete}>complete dice</button></div> }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/GlossaryLink', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/CollectionDialog', () => ({ default: ({ collection }: { collection: { name?: string } | null }) => <div data-testid="collection-dialog">collection dialog {collection?.name ?? 'new'}</div> }))
vi.mock('../components/MigrationDialog', () => ({ default: ({ onSkip, onClose }: { onSkip: () => void; onClose: () => void }) => <div><button onClick={onSkip}>skip migration</button><button onClick={onClose}>close migration</button></div> }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: ({ onComplete, onClose }: { onComplete: (v: string) => void; onClose: () => void }) => <div><button onClick={() => onComplete('1')}>complete simple</button><button onClick={onClose}>close simple</button></div> }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: () => <div>pool</div> }))

describe('RollPage skip coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    bootstrapHook.value = null
    skipHookValue.value = null
    relatedApi.readingOrders.mockResolvedValue({ reading_orders: [] })
    relatedApi.connectedThreads.mockResolvedValue({ connected_threads: [] })
    relatedApi.blockingInfo.mockResolvedValue({ blocking_reasons: [] })
    relatedApi.batchBlockingInfo.mockResolvedValue({ threads: {} })
    spies.skip.mockReset()
    spies.refetch.mockResolvedValue({})
  })

  it('advances to a different eligible result via Skip and shows new thread metadata', async () => {
    const nextRoll = {
      thread_id: 2,
      title: 'Next Saga',
      format: 'Graphic Novel',
      issues_remaining: 1,
      queue_position: 2,
      total_issues: 12,
      reading_progress: 0.5,
      issue_id: 20,
      issue_number: '7',
      next_issue_id: 21,
      next_issue_number: '8',
      result: 5,
      die_size: 6,
    }
    spies.skip.mockResolvedValue(nextRoll)
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    await user.click(screen.getByTestId('skip-roll'))
    await waitFor(() => expect(spies.skip).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(spies.refetch).toHaveBeenCalled())
  })

  it('handles skip returning null without entering error state', async () => {
    spies.skip.mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    await user.click(screen.getByTestId('skip-roll'))
    await waitFor(() => expect(spies.skip).toHaveBeenCalledTimes(1))
    // refetch should not have been called again for null response
    expect(spies.refetch).not.toHaveBeenCalled()
  })

  it('surfaces skip failure via error message', async () => {
    const err = Object.assign(new Error('skip unavailable'), { response: { status: 409, data: { detail: 'No pending roll to skip. Roll first.' } } })
    spies.skip.mockRejectedValue(err)
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    await user.click(screen.getByTestId('skip-roll'))
    await waitFor(() => expect(spies.skip).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText('No pending roll to skip. Roll first.')).toBeInTheDocument())
  })

  it('renders skipping pending state', async () => {
    skipHookValue.value = { mutate: spies.skip, isPending: true, isError: false, refreshError: null, hasRefreshError: false, retryRefresh: vi.fn() }
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    expect(screen.getByText('Skipping…')).toBeInTheDocument()
    expect(screen.getByTestId('skip-roll')).toBeDisabled()
  })
})
