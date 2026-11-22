/**
 * Issue #4768: the Roll die must be derived during render from the scoped
 * die-state query (single source of truth), never copied into page state by a
 * `useEffect` from bootstrap/server data (#4352 follow-up audit).
 *
 * The behavioral cases render the real `RollPage` with a spy wrapped around
 * `RollHeader` that records the `currentDie` prop on EVERY render pass. An
 * effect-synced die starts from a local fallback (d6) and only reaches the
 * server die in a post-effect render, so the first recorded prop would be the
 * fallback; render derivation records the server die on the very first pass.
 *
 * The bootstrap fixtures below still carry the retired `current_die` /
 * `manual_die` wire fields (dropped from the contract by #4820) with values
 * that disagree with the scoped die, proving no code path reads them.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import {
  useRollDieState,
  useRollEligibleIssueIds,
  useRollIssueCards,
} from '../hooks/useRollResources'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { ToastProvider } from '../contexts/ToastProvider'
import {
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { useSnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { writeRollSnoozes } from '../services/api-roll'
import { cast } from '../utils/cast'

// Records the `currentDie` prop RollPage passes to RollHeader on every render
// pass, so an effect-synced die (fallback on first pass) is distinguishable
// from a render-derived one (server die on first pass).
// SAFETY: `as number[]` only types the hoisted accumulator that the RollHeader spy pushes `currentDie` into; the array starts empty and only numbers are pushed.
const headerCurrentDieProps = vi.hoisted(() => [] as number[])

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides }: { sides: number }) => <div data-testid="lazy-dice" data-sides={sides} />,
}))

vi.mock('../components/GlossaryLink', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../pages/RollPage/components/RollHeader', async (importOriginal) => {
  // SAFETY: importOriginal generic only types the mocked module's shape so the spy wrapper can spread the real component's props; no runtime assertion occurs.
  const actual = await importOriginal<typeof import('../pages/RollPage/components/RollHeader')>()
  return {
    RollHeader: (props: React.ComponentProps<typeof actual.RollHeader>) => {
      headerCurrentDieProps.push(props.currentDie)
      return <actual.RollHeader {...props} />
    },
  }
})

vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: vi.fn() }))
vi.mock('../hooks/useRollResources', () => ({
  useRollDieState: vi.fn(),
  useRollEligibleIssueIds: vi.fn(),
  useRollIssueCards: vi.fn(),
}))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useUnsnooze: () => ({ mutate: vi.fn().mockResolvedValue({}), isPending: false }),
  useSetDie: vi.fn(),
  useResetDice: () => ({ mutate: vi.fn().mockResolvedValue({ die: 6, replayed: false }), isPending: false }),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn() }))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useShuffleQueue: vi.fn(),
  useActiveSeriesCount: () => null,
}))
vi.mock('../hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks')>()
  return { ...actual, useRate: vi.fn() }
})
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../services/api-threads', () => ({
  threadsApi: {
    list: vi.fn().mockResolvedValue({ threads: [], next_page_token: null }),
    setPending: vi.fn(),
  },
}))
vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    threadsApi: {
      list: vi.fn().mockResolvedValue({ threads: [], next_page_token: null }),
      setPending: vi.fn(),
    },
    dependenciesApi: {
      getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})

// SAFETY: vi.mocked returns a typed mock whose mockReturnValue surface matches the hook; cast preserves the mock call API.
const mockedUseRollBootstrap = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollBootstrap))
// SAFETY: Same mock-shape widening for the scoped resource hooks; safe because the test only reads their return objects.
const mockedUseRollEligibleIssueIds = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollEligibleIssueIds))
const mockedUseRollIssueCards = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollIssueCards))
const mockedUseRollDieState = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollDieState))
// SAFETY: Same mock-shape widening for the restore hook; safe because the test only reads the mocked return object.
const mockedUseBugReportRestore = cast<ReturnType<typeof vi.fn>>(vi.mocked(useBugReportRestore))

// Legacy wire fields (`current_die`, `manual_die`) are deliberately present
// with values that disagree with the scoped die: the retired bootstrap die
// projection must never reach the page (#4820), so these values are inert.
const bootstrap = {
  session_id: 1,
  user_id: 1,
  current_die: 8,
  manual_die: 20,
  pending_thread_id: null,
  last_rolled_result: null,
  active_thread: null,
  roll_pool: [
    { id: 1, title: 'Saga', format: 'Comic' },
    { id: 2, title: 'X-Men', format: 'Comic' },
  ],
  snoozed_threads: [],
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
}

const SCOPED_DIE_20 = {
  die: 20,
  ladder: [2, 4, 6, 8, 10, 12, 20],
  default_die: 6,
  last_roll: null,
}

function renderRollPage() {
  return render(
    <ToastProvider>
      <RollPage />
    </ToastProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  headerCurrentDieProps.length = 0
  writeRollSnoozes([])
  mockedUseRollDieState.mockReturnValue({ data: undefined })
  mockedUseRollEligibleIssueIds.mockReturnValue({ data: undefined })
  mockedUseRollIssueCards.mockReturnValue({ data: undefined })
  mockedUseRollBootstrap.mockReturnValue({
    data: bootstrap,
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })
  mockedUseBugReportRestore.mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  })

  // SAFETY: Test stubs for the mutation hooks; stub shapes match the mutation returns and are only read for isPending/mutate.
  vi.mocked(useSetDie).mockReturnValue(cast<ReturnType<typeof useSetDie>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useRoll).mockReturnValue(cast<ReturnType<typeof useRoll>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useOverrideRoll).mockReturnValue(cast<ReturnType<typeof useOverrideRoll>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useDismissPending).mockReturnValue(cast<ReturnType<typeof useDismissPending>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useSnooze).mockReturnValue(cast<ReturnType<typeof useSnooze>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useMoveToFront).mockReturnValue(cast<ReturnType<typeof useMoveToFront>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useMoveToBack).mockReturnValue(cast<ReturnType<typeof useMoveToBack>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useShuffleQueue).mockReturnValue(cast<ReturnType<typeof useShuffleQueue>>({ mutate: vi.fn(), isPending: false }))
  vi.mocked(useRate).mockReturnValue(cast<ReturnType<typeof useRate>>({ mutate: vi.fn(), isPending: false }))
})

describe('Roll die is render-derived from scoped die-state (#4768)', () => {
  it('passes the scoped die on the very first render pass, never a fallback (#4768)', () => {
    mockedUseRollDieState.mockReturnValue({ data: SCOPED_DIE_20, isError: false })

    renderRollPage()

    // The spy saw at least one header render, and every single one carried
    // the scoped d20. An effect syncing server data into state would record
    // the d6 fallback on the first pass before the effect fires.
    expect(headerCurrentDieProps.length).toBeGreaterThan(0)
    expect(headerCurrentDieProps).toEqual(
      headerCurrentDieProps.map(() => 20),
    )
    expect(screen.getByRole('button', { name: 'd20' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: /^current die d20$/i })).toBeInTheDocument()
    for (const die of screen.getAllByTestId('lazy-dice')) {
      expect(die).toHaveAttribute('data-sides', '20')
    }
  })

  it('never reads the retired bootstrap current_die/manual_die wire fields (#4768)', () => {
    // Bootstrap claims d8/d20 via the retired projection; the scoped die (d12)
    // is the only value allowed to reach the header on any render pass.
    mockedUseRollDieState.mockReturnValue({
      data: { die: 12, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
      isError: false,
    })

    renderRollPage()

    expect(headerCurrentDieProps.length).toBeGreaterThan(0)
    for (const die of headerCurrentDieProps) {
      expect(die).toBe(12)
    }
    expect(screen.getByRole('button', { name: 'd12' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('derives the d6 default on the first render while the scoped query is unsettled (#4768)', () => {
    mockedUseRollDieState.mockReturnValue({ data: undefined, isError: false })

    renderRollPage()

    expect(headerCurrentDieProps.length).toBeGreaterThan(0)
    for (const die of headerCurrentDieProps) {
      expect(die).toBe(6)
    }
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('falls back to d6 on the first render when the scoped query errored (#4768)', () => {
    // RollPage maps a failed scoped refresh to `undefined` (stale-data guard),
    // so the derivation default applies immediately, not after an effect.
    mockedUseRollDieState.mockReturnValue({ data: SCOPED_DIE_20, isError: true })

    renderRollPage()

    expect(headerCurrentDieProps.length).toBeGreaterThan(0)
    for (const die of headerCurrentDieProps) {
      expect(die).toBe(6)
    }
  })
})

describe('Roll page state carries no server-die copy (#4768 audit)', () => {
  const SOURCE_ROOT = join(import.meta.dirname, '..')

  // `useRollPageState` may hold only client-owned values (UI toggles, in-flight
  // mutation state, pending-roll hydration). No die state or die setter may
  // exist there, and the bootstrap sync hook must stay redirect-only.
  const FORBIDDEN_IN_PAGE_STATE = ['currentDie', 'setCurrentDie', 'diceState', 'setDiceState', 'manual_die', 'current_die']
  const FORBIDDEN_IN_BOOTSTRAP_SYNC = ['setCurrentDie', 'manual_die', 'current_die', 'useState']

  it('useRollPageState declares no die state (#4768)', () => {
    const source = readFileSync(join(SOURCE_ROOT, 'pages/RollPage/useRollPageState.ts'), 'utf-8')
    const found = FORBIDDEN_IN_PAGE_STATE.filter((pattern) => source.includes(pattern))
    expect(found).toEqual([])
  })

  it('useRollBootstrapSync stays redirect-only with no die projection (#4768)', () => {
    const source = readFileSync(join(SOURCE_ROOT, 'pages/RollPage/useRollBootstrapSync.ts'), 'utf-8')
    const found = FORBIDDEN_IN_BOOTSTRAP_SYNC.filter((pattern) => source.includes(pattern))
    expect(found).toEqual([])
  })
})
