import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'
import { cast } from '../utils/cast'

const spies = vi.hoisted(() => ({
  refetch: vi.fn(), navigate: vi.fn(), list: vi.fn(),
}))

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }),
}))
vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: vi.fn(), isPending: false }),
  useClearManualDie: () => ({ mutate: vi.fn(), isPending: false }),
  useRoll: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissPending: () => ({ mutate: vi.fn(), isPending: false }),
  useOverrideRoll: () => ({ mutate: vi.fn(), isPending: false }),
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
vi.mock('../hooks/useSkip', () => ({
  useSkip: () => ({ mutate: vi.fn(), isPending: false }),
  useUnskip: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../services/api-taste', () => ({
  tasteApi: {
    getDiscoveries: vi.fn().mockResolvedValue({ discoveries: [], generated_at: new Date().toISOString() }),
    dismiss: vi.fn().mockResolvedValue({ dismissed: true }),
    submitVerdict: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../services/api', () => ({
  default: {},
  threadsApi: {
    list: spies.list,
    setPending: vi.fn(),
  },
  dependenciesApi: {
    getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
  skipApi: {
    skip: vi.fn().mockResolvedValue(undefined),
    unskip: vi.fn().mockResolvedValue(undefined),
  },
  sessionApi: {
    updateMode: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../components/LazyDice3D', () => ({
  default: () => <div data-testid="dice" />,
}))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/GlossaryLink', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: React.ReactNode }) =>
    isOpen ? <section><h2>{title}</h2>{children}</section> : null,
}))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: () => <div>pool</div> }))

// Emulates a pending roll for a d8 current die: useRollPendingSession hydrates
// the rating view with the default 3.0 rating on first paint, before the slider
// is touched (issue #2533 repro).
const pendingBootstrap = {
  session_id: 1,
  user_id: 1,
  current_die: 8,
  manual_die: null,
  pending_thread_id: 1,
  last_rolled_result: null,
  active_thread: {
    id: 1,
    title: 'Annihilation: Super-Skrull',
    format: 'Comic',
    issues_remaining: 6,
    queue_position: 2,
    total_issues: 12,
    reading_progress: 'in_progress',
    issue_id: null,
    issue_number: '1',
    next_issue_id: null,
    next_issue_number: '2',
    last_rolled_result: null,
  },
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
}

// SAFETY: The mocked useRollBootstrap return value is read by the page hooks;
// the cast reuses the same widening used across the RollPage test suite.
const mockedUseRollBootstrap = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollBootstrap))

function renderRollPage() {
  return render(
    <ToastProvider>
      <RollPage />
    </ToastProvider>,
  )
}

describe('RollPage initial rating preview (issue #2533 regression)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    spies.list.mockResolvedValue({ threads: [], next_page_token: null })
    spies.refetch.mockResolvedValue({})
    mockedUseRollBootstrap.mockReturnValue({
      data: pendingBootstrap,
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    })
  })

  it('shows d8 → d10 on first paint for a d8 current die at the default 3.0 rating', () => {
    renderRollPage()

    expect(screen.getByText('d8 → d10')).toBeInTheDocument()
    expect(screen.queryByText('d8 → d8')).not.toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
    expect(screen.getByText('Moves this series beyond the next roll range.')).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: /rating from 0.5 to 5.0/i })).toHaveValue('3')
  })

  it('keeps the correct projection after the slider is nudged and returned to 3.0', () => {
    renderRollPage()

    expect(screen.getByText('d8 → d10')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('slider', { name: /rating from 0.5 to 5.0/i }), {
      target: { value: '4.0' },
    })
    expect(screen.getByText('d8 → d6')).toBeInTheDocument()
    expect(screen.getByText('More focused next roll')).toBeInTheDocument()
    expect(screen.getByText('Moves this series to the front of the queue.')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('slider', { name: /rating from 0.5 to 5.0/i }), {
      target: { value: '3.0' },
    })

    expect(screen.getByText('d8 → d10')).toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
    expect(screen.getByText('Moves this series beyond the next roll range.')).toBeInTheDocument()
  })
})
