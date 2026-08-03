import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
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

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides }: { sides: number }) => <div data-testid="lazy-dice" data-sides={sides} />,
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
  const actual = await importOriginal<Record<string, unknown>>()
  return { ...actual, useRate: vi.fn() }
})
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    threadsApi: {
      list: vi.fn().mockResolvedValue({ threads: [] }),
      setPending: vi.fn(),
    },
    dependenciesApi: {
      getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})

const mockedUseRollBootstrap = vi.mocked(useRollBootstrap) as any
const mockedUseBugReportRestore = vi.mocked(useBugReportRestore) as any

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
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
}

beforeEach(() => {
  navigateSpy.mockReset()
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

  vi.mocked(useSetDie).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useClearManualDie).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useRoll).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useOverrideRoll).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useDismissPending).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useSnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useUnsnooze).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToFront).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useMoveToBack).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useShuffleQueue).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useRate).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
})

it('renders the bounded bootstrap pool without Collections state', () => {
  render(<RollPage />)

  expect(screen.getByText('Pile Roller')).toBeInTheDocument()
  expect(screen.getByLabelText('Roll pool')).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('X-Men')).toBeInTheDocument()
  expect(screen.queryByText(/collection/i)).not.toBeInTheDocument()
})

it('opens the retained thread action sheet from a bootstrap pool item', async () => {
  const user = userEvent.setup()
  render(<RollPage />)

  await user.click(screen.getByText('Saga'))

  expect(screen.getByText('Read Now')).toBeInTheDocument()
  expect(screen.getByText('Move to Front')).toBeInTheDocument()
  expect(screen.getByText('Move to Back')).toBeInTheDocument()
  expect(screen.getByText('Snooze')).toBeInTheDocument()
  expect(screen.getByText('Edit Thread')).toBeInTheDocument()
})

it('loads full thread choices only after the Override modal opens', async () => {
  const user = userEvent.setup()
  vi.mocked(threadsApi.list).mockResolvedValueOnce({
    threads: [{ id: 9, title: 'Override Choice', format: 'Comic', status: 'active' }],
  } as any)

  render(<RollPage />)
  expect(threadsApi.list).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: /override/i }))

  await waitFor(() => expect(threadsApi.list).toHaveBeenCalledWith({ page_size: 200 }))
  expect(await screen.findByRole('option', { name: 'Override Choice (Comic)' })).toBeInTheDocument()
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

  render(<RollPage />)
  expect(screen.getByText('Session Error')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalled()
})
