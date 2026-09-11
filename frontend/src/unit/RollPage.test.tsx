import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { ToastProvider } from '../contexts/ToastProvider'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { threadsApi } from '../services/api'
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
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: vi.fn(), useUnsnooze: vi.fn() }))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useShuffleQueue: vi.fn(),
}))
vi.mock('../hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks')>()
  return { ...actual, useRate: vi.fn() }
})
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
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
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
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
  // SAFETY: Test stub for useClearManualDie; cast is safe because only mutate/isPending are accessed.
  vi.mocked(useClearManualDie).mockReturnValue(cast<ReturnType<typeof useClearManualDie>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useRoll; minimal stub preserves the mutation contract used by the component.
  vi.mocked(useRoll).mockReturnValue(cast<ReturnType<typeof useRoll>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useOverrideRoll; safe widening for the mocked hook return.
  vi.mocked(useOverrideRoll).mockReturnValue(cast<ReturnType<typeof useOverrideRoll>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useDismissPending; only mutate/isPending are observed.
  vi.mocked(useDismissPending).mockReturnValue(cast<ReturnType<typeof useDismissPending>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useSnooze; stub matches the hook's mutation surface.
  vi.mocked(useSnooze).mockReturnValue(cast<ReturnType<typeof useSnooze>>({ mutate: vi.fn(), isPending: false }))
  // SAFETY: Test stub for useUnsnooze; safe because test harness only invokes mutate.
  vi.mocked(useUnsnooze).mockReturnValue(cast<ReturnType<typeof useUnsnooze>>({ mutate: vi.fn(), isPending: false }))
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
  expect(screen.getByLabelText(/2 ready to read, 2 mapped results/i)).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('X-Men')).toBeInTheDocument()
  expect(screen.queryByText(/collection/i)).not.toBeInTheDocument()
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

it('explains automatic and manual die modes on mobile', async () => {
  const user = userEvent.setup()
  renderRollPage()

  const dieControl = screen.getByRole('button', { name: /current die d6, automatic mode/i })
  expect(dieControl).toHaveTextContent('Auto')
  await user.click(dieControl)
  expect(screen.getByText(/automatic mode is active at d6/i)).toBeInTheDocument()
  const dieModal = screen.getByRole('dialog', { name: 'Select Die' })
  expect(within(dieModal).getByRole('button', { name: /^auto$/i })).toBeInTheDocument()
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
