import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
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
import { threadsApi } from '../services/api-threads'
import { writeRollSnoozes } from '../services/api-roll'
import { cast } from '../utils/cast'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides }: { sides: number }) => <div data-testid="lazy-dice" data-sides={sides} />,
}))

vi.mock('../components/GlossaryLink', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../hooks/useRollBootstrap', () => ({ useRollBootstrap: vi.fn() }))
vi.mock('../hooks/useRollResources', () => ({
  useRollDieState: vi.fn(),
  useRollEligibleIssueIds: vi.fn(),
  useRollIssueCards: vi.fn(),
}))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
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

const bootstrap = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
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

function renderRollPage() {
  return render(
    <ToastProvider>
      <RollPage />
    </ToastProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
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

  // SAFETY: Test stub for useSetDie; stub shape matches the hook's mutation return and is only read for isPending/mutate.
  vi.mocked(useSetDie).mockReturnValue(cast<ReturnType<typeof useSetDie>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useRoll; minimal stub preserves the mutation contract used by the component.
  vi.mocked(useRoll).mockReturnValue(cast<ReturnType<typeof useRoll>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useOverrideRoll; safe widening for the mocked hook return.
  vi.mocked(useOverrideRoll).mockReturnValue(cast<ReturnType<typeof useOverrideRoll>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useDismissPending; only mutate/isPending are observed.
  vi.mocked(useDismissPending).mockReturnValue(cast<ReturnType<typeof useDismissPending>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useSnooze; stub matches the hook's mutation surface.
  vi.mocked(useSnooze).mockReturnValue(cast<ReturnType<typeof useSnooze>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useMoveToFront; minimal shape covers the exercised mutation.
  vi.mocked(useMoveToFront).mockReturnValue(cast<ReturnType<typeof useMoveToFront>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useMoveToBack; cast preserves the hook's return contract for the test.
  vi.mocked(useMoveToBack).mockReturnValue(cast<ReturnType<typeof useMoveToBack>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useShuffleQueue; stub is sufficient for the rendered harness.
  vi.mocked(useShuffleQueue).mockReturnValue(cast<ReturnType<typeof useShuffleQueue>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useRate; cast is safe because only mutate/isPending are read.
  vi.mocked(useRate).mockReturnValue(cast<ReturnType<typeof useRate>>({ mutate: vi.fn(), isPending: false }))
})

it('renders the bounded bootstrap pool without Collections state', () => {
  renderRollPage()

  expect(screen.getByText('Roll')).toBeInTheDocument()
  expect(screen.getByLabelText(/2 in play, 2 mapped results/i)).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('X-Men')).toBeInTheDocument()
  expect(screen.queryByText(/collection/i)).not.toBeInTheDocument()
})

it('renders the scoped eligible order and passes browser snoozes to the resource (#4719)', () => {
  writeRollSnoozes([99])
  mockedUseRollEligibleIssueIds.mockReturnValue({
    data: { die: 6, issue_ids: [201], thread_ids: [2] },
  })

  renderRollPage()

  // The scoped endpoint owns which bootstrap faces are in play and their
  // order. Bootstrap still supplies each face's title/metadata.
  expect(mockedUseRollEligibleIssueIds).toHaveBeenCalledWith([99])
  expect(screen.getByLabelText(/1 in play, 1 mapped result/i)).toBeInTheDocument()
  expect(screen.getByText('X-Men')).toBeInTheDocument()
  expect(screen.queryByText('Saga')).not.toBeInTheDocument()
})

it('drives the pool cutoff and 3D die from scoped die-state when present (#4719)', () => {
  mockedUseRollBootstrap.mockReturnValue({
    data: {
      ...bootstrap,
      current_die: 20,
      roll_pool: [
        { id: 1, title: 'Saga', format: 'Comic' },
        { id: 2, title: 'X-Men', format: 'Comic' },
        { id: 3, title: 'Runaways', format: 'Comic' },
        { id: 4, title: 'Ultimate Spider-Man', format: 'Comic' },
      ],
    },
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })
  mockedUseRollDieState.mockReturnValue({
    data: { die: 2, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
  })

  renderRollPage()

  // Scoped die 2 bounds the visible pool even though bootstrap reports d20,
  // and both rendered dice use the scoped sides.
  expect(screen.getByLabelText(/2 in play, 2 mapped results/i)).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('X-Men')).toBeInTheDocument()
  expect(screen.queryByText('Runaways')).not.toBeInTheDocument()
  const dice = screen.getAllByTestId('lazy-dice')
  expect(dice.length).toBeGreaterThan(0)
  for (const die of dice) {
    expect(die).toHaveAttribute('data-sides', '2')
  }
})

it('requests one scoped card batch and prefers its title and issue number (#4719)', () => {
  mockedUseRollBootstrap.mockReturnValue({
    data: {
      ...bootstrap,
      roll_pool: [{
        id: 1,
        title: 'Bootstrap title',
        format: 'Comic',
        issue_id: 11,
        issue_number: '1',
      }],
    },
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })
  mockedUseRollEligibleIssueIds.mockReturnValue({
    data: { die: 6, issue_ids: [11], thread_ids: [1] },
  })
  mockedUseRollIssueCards.mockReturnValue({
    data: {
      items: [{
        issue_id: 11,
        thread_id: 1,
        thread_title: 'Canonical card title',
        issue_number: '9',
        status: 'unread',
        has_confirmed_identity: true,
        mapping_state: 'confirmed',
      }],
    },
  })

  renderRollPage()

  expect(mockedUseRollIssueCards).toHaveBeenCalledWith([11])
  expect(screen.getByText('Canonical card title')).toBeInTheDocument()
  expect(screen.getByText('#9')).toBeInTheDocument()
  expect(screen.queryByText('Bootstrap title')).not.toBeInTheDocument()
})

it('ignores retired diagnostic reports while retaining the active pool (#4441)', () => {
  mockedUseRollBootstrap.mockReturnValue({
    data: {
      ...bootstrap,
      pool_reason: 'all_blocked',
    },
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })

  renderRollPage()

  expect(screen.queryByText('287 series waiting for earlier issues')).not.toBeInTheDocument()
  expect(screen.queryByText('23 series out of the roll pool')).not.toBeInTheDocument()
  expect(screen.queryByText('2 series waiting for earlier issues')).not.toBeInTheDocument()
  expect(screen.queryByText('1 series out of the roll pool')).not.toBeInTheDocument()
  expect(screen.getByLabelText(/2 in play, 2 mapped results/i)).toBeInTheDocument()
})

it('opens the retained thread action sheet from a bootstrap pool item', async () => {
  const user = userEvent.setup()
  renderRollPage()

  await user.click(screen.getByText('Saga'))

  expect(screen.getByText('Read Now')).toBeInTheDocument()
  expect(screen.getByText('Move to Front')).toBeInTheDocument()
  expect(screen.getByText('Move to Back')).toBeInTheDocument()
  expect(screen.getByText('Snooze')).toBeInTheDocument()
  expect(screen.getByText('Edit Series')).toBeInTheDocument()
})

it('loads every active override page only after the modal opens', async () => {
  const user = userEvent.setup()
  // SAFETY: Mocked threadsApi.list payload matches the paginated thread shape exercised by the test; the cast narrows the literal to the API response type.
  vi.mocked(threadsApi.list)
    .mockResolvedValueOnce(cast<Awaited<ReturnType<typeof threadsApi.list>>>({
      threads: [{ id: 9, title: 'First Choice', format: 'Comic', status: 'active' }],
      next_page_token: 'page-2',
    }))
    // SAFETY: Second page uses the same paginated shape; safe because only threads/next_page_token are read.
    .mockResolvedValueOnce(cast<Awaited<ReturnType<typeof threadsApi.list>>>({
      threads: [{ id: 10, title: 'Second Choice', format: 'Comic', status: 'active' }],
      next_page_token: null,
    }))

  renderRollPage()
  expect(threadsApi.list).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: /pick manually/i }))

  await waitFor(() => expect(threadsApi.list).toHaveBeenCalledTimes(2))
  expect(threadsApi.list).toHaveBeenNthCalledWith(1, { page_size: 200 }, undefined)
  expect(threadsApi.list).toHaveBeenNthCalledWith(2, { page_size: 200 }, 'page-2')
  expect(await screen.findByRole('option', { name: 'First Choice (Comic)' })).toBeInTheDocument()
  expect(await screen.findByRole('option', { name: 'Second Choice (Comic)' })).toBeInTheDocument()
})

it('uses the scoped die in the die-selection modal when bootstrap differs (#4719)', async () => {
  const user = userEvent.setup()
  mockedUseRollBootstrap.mockReturnValue({
    data: { ...bootstrap, current_die: 8 },
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })
  mockedUseRollDieState.mockReturnValue({
    data: { die: 2, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
    isError: false,
  })

  renderRollPage()
  await user.click(screen.getByRole('button', { name: /^current die d2$/i }))
  const dieModal = screen.getByRole('dialog', { name: 'Select Die' })
  expect(within(dieModal).getByText(/die is currently d2/i)).toBeInTheDocument()
  for (const die of screen.getAllByTestId('lazy-dice')) {
    expect(die).toHaveAttribute('data-sides', '2')
  }
})

it('falls back to the reconciled bootstrap die after a scoped refetch error (#4719)', async () => {
  const user = userEvent.setup()
  mockedUseRollBootstrap.mockReturnValue({
    data: { ...bootstrap, current_die: 8 },
    refetch: vi.fn().mockResolvedValue(bootstrap),
    isPending: false,
    isError: false,
    error: null,
  })
  // TanStack retains stale successful data alongside isError on a failed refetch.
  mockedUseRollDieState.mockReturnValue({
    data: { die: 2, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
    isError: true,
  })

  renderRollPage()
  await user.click(screen.getByRole('button', { name: /^current die d8$/i }))
  const dieModal = screen.getByRole('dialog', { name: 'Select Die' })
  expect(within(dieModal).getByText(/die is currently d8/i)).toBeInTheDocument()
  for (const die of screen.getAllByTestId('lazy-dice')) {
    expect(die).toHaveAttribute('data-sides', '8')
  }
})

it('names the mobile die control for the event-derived die without an Auto mode (#4353)', async () => {
  const user = userEvent.setup()
  renderRollPage()

  const dieControl = screen.getByRole('button', { name: /^current die d6$/i })
  expect(dieControl).not.toHaveTextContent('Auto')
  await user.click(dieControl)
  const dieModal = screen.getByRole('dialog', { name: 'Select Die' })
  expect(within(dieModal).queryByRole('button', { name: /^auto$/i })).not.toBeInTheDocument()
})

it('shows a retry action when bootstrap loading fails', async () => {
  const user = userEvent.setup()
  const refetch = vi.fn()
  mockedUseRollBootstrap.mockReturnValue({
    data: null,
    refetch,
    isPending: false,
    isError: true,
    error: new Error('bootstrap unavailable'),
  })

  renderRollPage()
  expect(screen.getByText('Session Error')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalled()
})
