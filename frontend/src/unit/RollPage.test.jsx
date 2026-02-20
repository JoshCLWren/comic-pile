import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useClearManualDie, useOverrideRoll, useRoll, useSetDie } from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'
import { useRate } from '../hooks'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  }
})

vi.mock('../components/LazyDice3D', () => ({
  default: () => <div data-testid="lazy-dice" />,
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useStaleThreads: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
}))
vi.mock('../hooks', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    useRate: vi.fn(),
  }
})

beforeEach(() => {
  const mockSessionData = {
    current_die: 6,
    last_rolled_result: null,
    manual_die: null,
    has_restore_point: false,
    snoozed_threads: [],
  }
  useSession.mockReturnValue({
    data: mockSessionData,
    refetch: vi.fn(),
  })
  useThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comic', status: 'active' },
      { id: 2, title: 'X-Men', format: 'Comic', status: 'active' },
    ],
    refetch: vi.fn()
  })
  useStaleThreads.mockReturnValue({ data: [] })
  useSetDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useClearManualDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useOverrideRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useRate.mockReturnValue({ mutate: vi.fn(), isPending: false })
})

afterEach(() => {
  vi.restoreAllMocks()
})

it('renders roll page content and opens override modal', async () => {
  const user = userEvent.setup()
  render(<RollPage />)

  expect(screen.getByText('Pile Roller')).toBeInTheDocument()
  expect(screen.getByText('Tap Die to Roll')).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /override/i }))
  expect(screen.getByRole('heading', { name: /override roll/i })).toBeInTheDocument()
})

describe('Action Sheet', () => {
  const mockSnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockUnsnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockRefetchSession = vi.fn()
  const mockRefetchThreads = vi.fn()

  beforeEach(() => {
    mockSnoozeMutation.mutate.mockReset()
    mockUnsnoozeMutation.mutate.mockReset()
    useSnooze.mockReturnValue(mockSnoozeMutation)
    useUnsnooze.mockReturnValue(mockUnsnoozeMutation)
    useSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: mockRefetchSession,
    })
    useThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active' },
        { id: 2, title: 'X-Men', format: 'Comic', status: 'active' },
      ],
      refetch: mockRefetchThreads,
    })
  })

  it('opens action sheet when clicking pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    expect(screen.getByText('Read Now')).toBeInTheDocument()
    expect(screen.getByText('Move to Front')).toBeInTheDocument()
    expect(screen.getByText('Move to Back')).toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(screen.getByText('Edit Thread')).toBeInTheDocument()
  })

  it('calls snooze mutation when thread is not snoozed', async () => {
    const { threadsApi } = await import('../services/api')
    const setPendingSpy = vi.spyOn(threadsApi, 'setPending').mockResolvedValue({})

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    expect(setPendingSpy).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).toHaveBeenCalled()
    expect(mockUnsnoozeMutation.mutate).not.toHaveBeenCalled()

    setPendingSpy.mockRestore()
  })

  it('calls unsnooze mutation when thread is snoozed', async () => {
    useSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [{ id: 1, title: 'Saga', format: 'Comic' }],
      },
      refetch: mockRefetchSession,
    })
    mockUnsnoozeMutation.mutate.mockReset()

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const unsnoozeButton = screen.getByText('Unsnooze')
    await user.click(unsnoozeButton)

    expect(mockUnsnoozeMutation.mutate).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('navigates to /queue with editThreadId state when edit action is clicked', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const editButton = screen.getByText('Edit Thread')
    await user.click(editButton)

    expect(navigateSpy).toHaveBeenCalledWith('/queue', { state: { editThreadId: 1 } })
  })

  it('refetches threads and session after move-front action', async () => {
    const mockMoveToFront = { mutate: vi.fn(), isPending: false }
    useMoveToFront.mockReturnValue(mockMoveToFront)

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const moveFrontButton = screen.getByText('Move to Front')
    await user.click(moveFrontButton)

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })

  it('refetches threads and session after move-back action', async () => {
    const mockMoveToBack = { mutate: vi.fn(), isPending: false }
    useMoveToBack.mockReturnValue(mockMoveToBack)

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const moveBackButton = screen.getByText('Move to Back')
    await user.click(moveBackButton)

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })
})

describe('Keyboard Accessibility', () => {
  it('opens action sheet when pressing Enter on pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    sagaPoolItem.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })

  it('opens action sheet when pressing Space on pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    sagaPoolItem.focus()
    await user.keyboard(' ')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })
})

describe('Rating View', () => {
  it('shows rating view after a successful roll', async () => {
    const mockRoll = vi.fn().mockResolvedValue({
      result: 4,
      thread_id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5
    })
    useRoll.mockReturnValue({ mutate: mockRoll, isPending: false })

    // Simulate initial state
    useSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 4,
        manual_die: null,
        active_thread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 5 }
      },
      refetch: vi.fn()
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const diceElement = screen.getByLabelText('Roll the dice')
    await user.click(diceElement)

    // Wait for the roll timeout (400ms in code + 80ms interval)
    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('Excellent! Die steps down 🎲 Move to front (d4)')).toBeInTheDocument()
      expect(screen.getByText('Saga')).toBeInTheDocument()
    }, { timeout: 2000 })
  })

  it('shows rating view after clicking Read Now', async () => {
    const { threadsApi } = await import('../services/api')
    const setPendingSpy = vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      result: 3,
      thread_id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5
    })

    useSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 3,
        manual_die: null,
        active_thread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 5 }
      },
      refetch: vi.fn()
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaPoolItem)

    const readNowButton = screen.getByText('Read Now')
    await user.click(readNowButton)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('Saga')).toBeInTheDocument()
    })

    setPendingSpy.mockRestore()
  })

  it('[P1] uses immediate metadata from API instead of stale session data', async () => {
    const { threadsApi } = await import('../services/api')
    const freshMetadata = {
      thread_id: 2,
      title: 'Fresh X-Men',
      format: 'HC',
      issues_remaining: 10,
      result: 5
    }
    const setPendingSpy = vi.spyOn(threadsApi, 'setPending').mockResolvedValue(freshMetadata)

    // Session still shows Saga (ID 1) as active_thread
    useSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 1,
        active_thread: { id: 1, title: 'Old Saga', format: 'Comic', issues_remaining: 5 }
      },
      refetch: vi.fn()
    })

    const user = userEvent.setup()
    render(<RollPage />)

    // Click X-Men in pool
    const xmenPoolItem = screen.getByText('X-Men').closest('[role="button"]')
    await user.click(xmenPoolItem)

    const readNowButton = screen.getByText('Read Now')
    await user.click(readNowButton)

    await waitFor(() => {
      // Should show "Fresh X-Men" even though session says "Old Saga"
      expect(screen.getByText('Fresh X-Men')).toBeInTheDocument()
      expect(screen.getByText('HC')).toBeInTheDocument()
      expect(screen.getByText('10 Issues left')).toBeInTheDocument()
    })

    setPendingSpy.mockRestore()
  })

  it('[P2] resets rating to 4.0 when starting a new flow', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      result: 3,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5
    })

    const mockRate = vi.fn().mockResolvedValue({})
    useRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view for first thread
    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Change rating to 1.0 and save
    const input = screen.getByLabelText(/rating/i)
    fireEvent.change(input, { target: { value: '1.0' } })
    expect(screen.getByText('1.0')).toBeInTheDocument()

    await user.click(screen.getByText('Save & Continue'))

    // 3. Wait for rating view to close and roll view to return
    await waitFor(() => {
      expect(screen.queryByText('How was it?')).not.toBeInTheDocument()
    })

    // 4. Enter rating view again for same or another thread
    const sagaItem2 = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem2)
    const readNowButton = await screen.findByText('Read Now')
    await user.click(readNowButton)

    // 5. Verify it's back to 4.0, not stuck at 1.0
    expect(await screen.findByText('4.0')).toBeInTheDocument()
  })

  it('[P3] filters the rated thread from the pool display', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      title: 'Saga',
      result: 3
    })

    const user = userEvent.setup()
    render(<RollPage />)

    // Initially Saga is in pool
    expect(screen.getByText('Saga')).toBeInTheDocument()

    // Enter rating view for Saga
    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // In rating view, Saga should be HIDDEN from the pool at the bottom
    const poolContainer = screen.getByText('Roll Pool').parentElement.parentElement
    expect(within(poolContainer).queryByText('Saga')).not.toBeInTheDocument()
    // Other threads (X-Men) should still be there
    expect(within(poolContainer).getByText('X-Men')).toBeInTheDocument()
  })

  it('[P4] refetches threads after successful rating', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      result: 3,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5
    })

    const mockRate = vi.fn().mockResolvedValue({})
    useRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const mockRefetchThreads = vi.fn()
    useThreads.mockReturnValue({
      data: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }],
      refetch: mockRefetchThreads
    })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Submit rating
    await user.click(screen.getByText('Save & Continue'))

    // 3. Verify refetchThreads was called
    await waitFor(() => {
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })

  it('[P6] does not auto-finish session when rating the last issue', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      result: 3,
      title: 'Final Issue Thread',
      format: 'Comic',
      issues_remaining: 1 // Only 1 issue left
    })

    const mockRate = vi.fn().mockResolvedValue({})
    useRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Submit rating (Save & Continue)
    await user.click(screen.getByText('Save & Continue'))

    // 3. Verify mutate was called with finish_session: false
    await waitFor(() => {
      expect(mockRate).toHaveBeenCalledWith(expect.objectContaining({
        issues_read: 1,
        finish_session: false
      }))
    })
  })

  it('[P7] does not show Save & Finish Session action', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      result: 3,
      title: 'Ongoing Thread',
      format: 'Comic',
      issues_remaining: 5
    })

    const mockRate = vi.fn().mockResolvedValue({})
    useRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    expect(screen.queryByText('Save & Finish Session')).not.toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(mockRate).not.toHaveBeenCalled()
  })

  it('[P8] cancel clears rating view and roll-selection state', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      thread_id: 1,
      result: 3,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaItem = screen.getByText('Saga').closest('[role="button"]')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    await user.click(screen.getByText('Cancel'))

    expect(screen.getByText('Tap Die to Roll')).toBeInTheDocument()

    const selectedPoolItem = document.querySelector('.pool-thread-selected')
    expect(selectedPoolItem).toBeNull()
  })
})
