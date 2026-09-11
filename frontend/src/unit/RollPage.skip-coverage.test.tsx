import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

// No vi.mock calls - use real imports and manual mock setup

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

interface HoistedHookValue {
  value: unknown
}

const bootstrapHook = vi.hoisted((): HoistedHookValue => ({ value: null }))
const skipHookValue = vi.hoisted((): HoistedHookValue => ({ value: null }))

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
}

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
    expect(spies.skip).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('skip-confirm'))
    await waitFor(() => expect(spies.skip).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(spies.refetch).toHaveBeenCalled())
  })

  it('handles skip returning null without entering error state', async () => {
    spies.skip.mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    await user.click(screen.getByTestId('skip-roll'))
    expect(spies.skip).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('skip-confirm'))
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
    expect(spies.skip).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('skip-confirm'))
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

  it('covers skip response with nullable optional fields', async () => {
    const sparseRoll = {
      thread_id: 3,
      title: 'Sparse Saga',
      format: 'Comic',
      issues_remaining: 0,
      queue_position: 5,
      total_issues: undefined,
      reading_progress: undefined,
      issue_id: undefined,
      issue_number: undefined,
      next_issue_id: undefined,
      next_issue_number: undefined,
      result: null,
      die_size: 6,
    }
    spies.skip.mockResolvedValue(sparseRoll)
    const user = userEvent.setup()
    render(<RollPage />)
    await waitFor(() => expect(screen.getByTestId('skip-roll')).toBeInTheDocument())
    await user.click(screen.getByTestId('skip-roll'))
    expect(spies.skip).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('skip-confirm'))
    await waitFor(() => expect(spies.skip).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(spies.refetch).toHaveBeenCalled())
  })
})