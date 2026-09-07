import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }),
}))

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
  rate: vi.fn(),
  skip: vi.fn(),
  unskip: vi.fn().mockResolvedValue({}),
  setPending: vi.fn(),
}))
const bootstrapHook = vi.hoisted(() => ({ value: null as unknown }))
const relatedApi = vi.hoisted(() => ({
  readingOrders: vi.fn(),
  connectedThreads: vi.fn(),
  blockingInfo: vi.fn(),
  batchBlockingInfo: vi.fn(),
}))

const bootstrapData: any = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  session_mode: null,
  snoozed_threads: [],
  roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }],
  last_rolled_result: 4,
  pending_thread_id: 1,
  active_thread: {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 2,
    queue_position: 1,
    total_issues: 10,
    reading_progress: '25.0%',
    issue_id: 10,
    issue_number: '4',
    next_issue_id: 11,
    next_issue_number: '5',
  },
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
}

const rateResponse = {
  thread_id: 1,
  issues_remaining: 1,
  queue_position: 1,
  total_issues: 10,
  reading_progress: '30.0%',
  next_unread_issue_id: 12,
  next_unread_issue_number: '6',
}

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
  }),
}))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () =>
    bootstrapHook.value ??
    ({ data: bootstrapData, refetch: spies.refetch, isPending: false, isError: false, error: null }),
}))
vi.mock('../hooks/useThread', () => ({ useStaleThreads: () => ({ data: [], refetch: spies.refetch }) }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: spies.setDie, isPending: false }),
  useClearManualDie: () => ({ mutate: spies.clearDie, isPending: false }),
  useRoll: () => ({ mutate: spies.roll, isPending: false }),
  useDismissPending: () => ({ mutate: spies.dismissPending, isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.override, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: () => ({ mutate: spies.snooze, isPending: false }),
  useUnsnooze: () => ({ mutate: spies.unsnooze, isPending: false }),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: () => ({ mutate: spies.moveFront, isPending: false }),
  useMoveToBack: () => ({ mutate: spies.moveBack, isPending: false }),
  useShuffleQueue: () => ({ mutate: spies.shuffle, isPending: false }),
}))
vi.mock('../hooks', () => ({
  useRate: () => ({ mutate: spies.rate, isPending: false }),
}))
vi.mock('../hooks/useSkip', () => ({
  useSkip: () => ({ mutate: spies.skip, isPending: false, isError: false }),
  useUnskip: () => ({ mutate: spies.unskip, isPending: false, isError: false }),
}))
vi.mock('../services/api-taste', () => ({
  tasteApi: {
    getDiscoveries: vi.fn().mockResolvedValue({ discoveries: [], generated_at: new Date().toISOString() }),
    dismiss: vi.fn().mockResolvedValue({ dismissed: true }),
    submitVerdict: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../hooks/useReaderContext', () => ({
  useReaderContext: () => ({ context: null, isLoading: false, error: null, refetch: vi.fn() }),
}))
vi.mock('../services/api', () => ({
  default: {},
  threadsApi: { setPending: spies.setPending, list: vi.fn().mockResolvedValue({ threads: [], next_page_token: null }) },
  dependenciesApi: {
    getConnectedThreads: relatedApi.connectedThreads,
    getBlockingInfo: relatedApi.blockingInfo,
    getBatchBlockingInfo: relatedApi.batchBlockingInfo,
  },
}))
vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: relatedApi.readingOrders },
}))
vi.mock('../components/LazyDice3D', () => ({
  default: ({ onRollComplete }: { onRollComplete?: () => void }) => (
    <div data-testid="dice">
      <button type="button" onClick={onRollComplete}>
        complete dice
      </button>
    </div>
  ),
}))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/GlossaryLink', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

beforeEach(() => {
  vi.clearAllMocks()
  bootstrapHook.value = null
  relatedApi.readingOrders.mockResolvedValue({ reading_orders: [] })
  relatedApi.connectedThreads.mockResolvedValue({ connected_threads: [] })
  relatedApi.blockingInfo.mockResolvedValue({ blocking_reasons: [] })
  relatedApi.batchBlockingInfo.mockResolvedValue({ threads: {} })
  spies.refetch.mockResolvedValue({})
  spies.setPending.mockResolvedValue({
    thread_id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 2,
    queue_position: 1,
    total_issues: 10,
    issue_id: 10,
    issue_number: '4',
    next_issue_id: 11,
    next_issue_number: '5',
    result: 4,
  })
  spies.rate.mockImplementation(async () => {
    // Mirrors the real useRate reconciliation: after a successful rate the
    // pending roll is consumed, so the bootstrap no longer auto-opens a rating.
    bootstrapHook.value = {
      data: { ...bootstrapData, pending_thread_id: null },
      refetch: spies.refetch,
      isPending: false,
      isError: false,
      error: null,
    }
    return rateResponse
  })
})

describe('RollPage post-rate copy prompt', () => {
  it('shows a copy prompt after rating and copies the title + issue string', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('save-and-continue')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('Rating from 0.5 to 5.0 in steps of 0.5'), {
      target: { value: '2' },
    })

    await user.click(screen.getByTestId('save-and-continue'))

    await waitFor(() => expect(screen.getByTestId('post-rate-copy-prompt')).toBeInTheDocument())
    expect(screen.getByTestId('post-rate-copy-prompt')).toHaveTextContent(
      'You just rated Saga 5 a 2/5.',
    )

    const copyButton = screen.getByRole('button', { name: 'Copy Saga 5' })
    await user.click(copyButton)

    expect(writeText).toHaveBeenCalledWith('Saga 5')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  it('keeps die and roll flow reachable while the prompt is visible', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('save-and-continue')).toBeInTheDocument())

    await user.click(screen.getByTestId('save-and-continue'))
    await waitFor(() => expect(screen.getByTestId('post-rate-copy-prompt')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
    expect(screen.queryByTestId('save-and-continue')).not.toBeInTheDocument()
  })

  it('dismissing the prompt removes it without blocking the next roll', async () => {
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('save-and-continue')).toBeInTheDocument())

    await user.click(screen.getByTestId('save-and-continue'))
    await waitFor(() => expect(screen.getByTestId('post-rate-copy-prompt')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Dismiss rating saved notice' }))
    expect(screen.queryByTestId('post-rate-copy-prompt')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Roll the dice' })).toBeInTheDocument()
  })

  it('reports the failure/retry state when clipboard access is denied', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))

    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('save-and-continue')).toBeInTheDocument())

    await user.click(screen.getByTestId('save-and-continue'))
    await waitFor(() => expect(screen.getByTestId('post-rate-copy-prompt')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Copy Saga 5' }))
    expect(screen.getByText('Retry copy')).toBeInTheDocument()
    expect(screen.getByText(/Copy failed/)).toBeInTheDocument()
  })
})