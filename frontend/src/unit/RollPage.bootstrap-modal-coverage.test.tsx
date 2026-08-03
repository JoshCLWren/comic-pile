import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

const spies = vi.hoisted(() => ({
  list: vi.fn(), override: vi.fn(), refetch: vi.fn(), navigate: vi.fn(),
}))

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }),
}))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () => ({
    data: {
      current_die: 6,
      manual_die: null,
      last_rolled_result: null,
      pending_thread_id: null,
      active_thread: null,
      roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }],
      snoozed_threads: [{ id: 2, title: 'Watchmen', format: 'Comic' }],
      snoozed_count: 1,
      blocked_threads: [],
      blocked_count: 0,
      stale_thread: null,
      stale_thread_count: 0,
    },
    refetch: spies.refetch,
    isPending: false,
    isError: false,
    error: null,
  }),
}))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: vi.fn(), isPending: false }),
  useClearManualDie: () => ({ mutate: vi.fn(), isPending: false }),
  useRoll: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissPending: () => ({ mutate: vi.fn(), isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.override, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: () => ({ mutate: vi.fn(), isPending: false }),
  useUnsnooze: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: () => ({ mutate: vi.fn(), isPending: false }),
  useMoveToBack: () => ({ mutate: vi.fn(), isPending: false }),
  useShuffleQueue: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: vi.fn(), isPending: false }) }))
vi.mock('../services/api', () => ({
  threadsApi: {
    list: spies.list,
    setPending: vi.fn(),
  },
  dependenciesApi: {
    getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
}))
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../components/LazyDice3D', () => ({
  default: ({ onRollComplete }: { onRollComplete?: () => void }) => (
    <button type="button" onClick={onRollComplete}>complete dice</button>
  ),
}))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) =>
    isOpen ? <section><h2>{title}</h2><button type="button" onClick={onClose}>close modal</button>{children}</section> : null,
}))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: () => <div>pool</div> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: () => <div>rating</div> }))

describe('RollPage bootstrap modal coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    spies.list.mockResolvedValue({
      threads: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }],
      next_page_token: null,
    })
    spies.override.mockResolvedValue({})
    spies.refetch.mockResolvedValue({})
  })

  it('loads override choices, renders active and snoozed groups, and completes the dice callback', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    fireEvent.click(screen.getAllByRole('button', { name: 'complete dice' })[0]!)
    await user.click(screen.getByRole('button', { name: 'Override' }))

    await waitFor(() => expect(spies.list).toHaveBeenCalled())
    const select = screen.getByRole('combobox')
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Watchmen (Comic)' })).toBeInTheDocument()

    await user.selectOptions(select, '1')
    await user.click(screen.getByRole('button', { name: 'Override Roll' }))
    await waitFor(() => expect(spies.override).toHaveBeenCalledWith(1))
    expect(spies.refetch).toHaveBeenCalled()
  })
})
