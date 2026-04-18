import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
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
import { useCollections } from '../contexts/CollectionContext'
import { useBugReportRestore } from '../contexts/BugReportRestoreContext'
import { ToastProvider } from '../contexts/ToastContext'
import type { RollResponse } from '../types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides, value }: { sides: number; value: number }) => (
    <div data-testid="lazy-dice" data-sides={String(sides)} data-value={String(value)} />
  ),
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useStaleThreads: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useShuffleQueue: vi.fn(),
}))
vi.mock('../config/featureFlags', () => ({
  collectionsEnabled: true,
  isReviewsFeatureEnabled: vi.fn(() => true),
}))
vi.mock('../contexts/BugReportRestoreContext', () => ({ useBugReportRestore: vi.fn() }))
vi.mock('../hooks', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    useRate: vi.fn(),
  }
})
vi.mock('../contexts/CollectionContext', () => ({ useCollections: vi.fn() }))
vi.mock('../contexts/ToastContext', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}))

const mockedUseSession = vi.mocked(useSession) as any
const mockedUseThreads = vi.mocked(useThreads) as any
const mockedUseStaleThreads = vi.mocked(useStaleThreads) as any
const mockedUseSetDie = vi.mocked(useSetDie) as any
const mockedUseClearManualDie = vi.mocked(useClearManualDie) as any
const mockedUseRoll = vi.mocked(useRoll) as any
const mockedUseOverrideRoll = vi.mocked(useOverrideRoll) as any
const mockedUseDismissPending = vi.mocked(useDismissPending) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue) as any
const mockedUseRate = vi.mocked(useRate) as any
const mockedUseCollections = vi.mocked(useCollections) as any
const mockedUseBugReportRestore = vi.mocked(useBugReportRestore) as any

type MockThread = {
  id: number
  title: string
  format: string
  issues_remaining: number
  queue_position: number
  status?: string
  total_issues?: number | null
  reading_progress?: string | null
  last_rolled_result?: number | null
  next_issue_number?: string | null
  issue_number?: string | null
}

const baseRollResponse: RollResponse = {
  thread_id: 1,
  title: 'Saga',
  format: 'Comics',
  issues_remaining: 5,
  queue_position: 1,
  die_size: 6,
  result: 3,
  offset: 0,
  snoozed_count: 0,
  issue_id: null,
  issue_number: null,
  next_issue_id: null,
  next_issue_number: null,
  total_issues: 50,
  reading_progress: null,
}

function getPoolItem(title: string): HTMLElement {
  const element = screen.getByText(title).closest('[role="button"]')
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Pool item for ${title} not found`)
  }
  return element
}

beforeEach(() => {
  const mockSessionData = {
    current_die: 6,
    last_rolled_result: null,
    manual_die: null,
    has_restore_point: false,
    snoozed_threads: [],
  }
  mockedUseSession.mockReturnValue({
    data: mockSessionData,
    refetch: vi.fn(),
  })
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
      { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
    ],
    refetch: vi.fn()
  })
  mockedUseStaleThreads.mockReturnValue({ data: [] })
  mockedUseSetDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseClearManualDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseOverrideRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseDismissPending.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRate.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseCollections.mockReturnValue({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
  })
  mockedUseBugReportRestore.mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  })
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

it('registers a restore target while the override modal is open', async () => {
  const user = userEvent.setup()
  const restoreState = {
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  }
  mockedUseBugReportRestore.mockReturnValue(restoreState)

  render(<RollPage />)

  await user.click(screen.getByRole('button', { name: /override/i }))

  expect(restoreState.setRestoreAction).toHaveBeenCalled()

  await user.click(screen.getByLabelText('Close modal'))

  expect(restoreState.clearRestoreAction).toHaveBeenCalled()
})

describe('Action Sheet', () => {
  const mockSnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockUnsnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockRefetchSession = vi.fn()
  const mockRefetchThreads = vi.fn()

  beforeEach(() => {
    mockSnoozeMutation.mutate.mockReset()
    mockUnsnoozeMutation.mutate.mockReset()
    mockedUseSnooze.mockReturnValue(mockSnoozeMutation)
    mockedUseUnsnooze.mockReturnValue(mockUnsnoozeMutation)
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: mockRefetchSession,
    })
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
      ],
      refetch: mockRefetchThreads,
    })
  })

  it('opens action sheet when clicking pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    await user.click(sagaPoolItem)

    expect(screen.getByText('Read Now')).toBeInTheDocument()
    expect(screen.getByText('Move to Front')).toBeInTheDocument()
    expect(screen.getByText('Move to Back')).toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(screen.getByText('Edit Thread')).toBeInTheDocument()
  })

  it('calls snooze mutation when thread is not snoozed', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    await user.click(sagaPoolItem)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    expect(mockSnoozeMutation.mutate).toHaveBeenCalled()
    expect(mockUnsnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('calls unsnooze mutation when thread is snoozed', async () => {
    mockedUseSession.mockReturnValue({
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

    const snoozedToggleButton = screen.getByText(/Snoozed \(1\)/)
    await user.click(snoozedToggleButton)

    const unsnoozeButton = screen.getByLabelText('Unsnooze this comic')
    await user.click(unsnoozeButton)

    expect(mockUnsnoozeMutation.mutate).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('navigates to /queue with editThreadId state when edit action is clicked', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    await user.click(sagaPoolItem)

    const editButton = screen.getByText('Edit Thread')
    await user.click(editButton)

    expect(navigateSpy).toHaveBeenCalledWith('/queue', { state: { editThreadId: 1 } })
  })

  it('refetches threads and session after move-front action', async () => {
    const mockMoveToFront = { mutate: vi.fn(), isPending: false }
    mockedUseMoveToFront.mockReturnValue(mockMoveToFront)

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
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
    mockedUseMoveToBack.mockReturnValue(mockMoveToBack)

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    await user.click(sagaPoolItem)

    const moveBackButton = screen.getByText('Move to Back')
    await user.click(moveBackButton)

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })

  it('shuffles the roll pool from the header control', async () => {
    const mockShuffle = { mutate: vi.fn(), isPending: false }
    const mockRefetchThreads = vi.fn()
    mockedUseShuffleQueue.mockReturnValue(mockShuffle)
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
      ],
      refetch: mockRefetchThreads,
    })

    const user = userEvent.setup()
    render(<RollPage />)

    await user.click(screen.getByRole('button', { name: /shuffle/i }))

    await waitFor(() => {
      expect(mockShuffle.mutate).toHaveBeenCalled()
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })
})

describe('Keyboard Accessibility', () => {
  it('opens action sheet when pressing Enter on pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    sagaPoolItem.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })

  it('opens action sheet when pressing Space on pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
    sagaPoolItem.focus()
    await user.keyboard(' ')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })
})

describe('Rating View', () => {
  it('shows rating view after a successful roll', async () => {
    const mockRoll = vi.fn().mockResolvedValue({ ...baseRollResponse, result: 4 })
    mockedUseRoll.mockReturnValue({ mutate: mockRoll, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    const diceElement = screen.getByLabelText('Roll the dice')
    await user.click(diceElement)

    // Wait for the roll timeout (400ms in code + 80ms interval)
    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('Saga')).toBeInTheDocument()
    }, { timeout: 2000 })
  })

  it('shows rating view after clicking Read Now', async () => {
    const { threadsApi } = await import('../services/api')
    const setPendingSpy = vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 3,
        manual_die: null,
        active_thread: { id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5 }
      },
      refetch: vi.fn()
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = getPoolItem('Saga')
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
    const freshMetadata: RollResponse = {
      ...baseRollResponse,
      thread_id: 2,
      title: 'Fresh X-Men',
      format: 'HC',
      issues_remaining: 10,
      result: 5,
    }
    const setPendingSpy = vi.spyOn(threadsApi, 'setPending').mockResolvedValue(freshMetadata)

    // Session still shows Saga (ID 1) as active_thread
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 1,
        active_thread: { id: 1, title: 'Old Saga', format: 'Comics', issues_remaining: 5 }
      },
      refetch: vi.fn()
    })

    const user = userEvent.setup()
    render(<RollPage />)

    // Click X-Men in pool
    const xmenPoolItem = getPoolItem('X-Men')
    await user.click(xmenPoolItem)

    const readNowButton = screen.getByText('Read Now')
    await user.click(readNowButton)

    await waitFor(() => {
      // Should show "Fresh X-Men" even though session says "Old Saga"
      expect(screen.getByText('Fresh X-Men')).toBeInTheDocument()
      expect(screen.getByText('HC')).toBeInTheDocument()
      expect(screen.getByText('10 issues left')).toBeInTheDocument()
    })

    setPendingSpy.mockRestore()
  })

  it('[P2] resets rating to 3.0 when starting a new flow', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view for first thread
    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Change rating to 1.0 and save
    const input = screen.getByLabelText(/rating/i)
    fireEvent.change(input, { target: { value: '1.0' } })
    expect(screen.getByText('1.0')).toBeInTheDocument()

    await user.click(screen.getByText('Save & Continue'))

    // 3. Wait for ReviewForm modal to appear and click Skip
    await waitFor(() => {
      expect(screen.getByText('Write a Review?')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Skip'))

    // 4. Wait for rating view to close and roll view to return
    await waitFor(() => {
      expect(screen.queryByText('How was it?')).not.toBeInTheDocument()
    })

    // 4. Enter rating view again for same or another thread
    const sagaItem2 = getPoolItem('Saga')
    await user.click(sagaItem2)
    const readNowButton = await screen.findByText('Read Now')
    await user.click(readNowButton)

    // 5. Verify it's back to 3.0, not stuck at 1.0
    expect(await screen.findByText('3.0')).toBeInTheDocument()
  })

  it('[P3] filters the rated thread from the pool display', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const user = userEvent.setup()
    render(<RollPage />)

    // Initially Saga is in pool
    expect(screen.getByText('Saga')).toBeInTheDocument()

    // Enter rating view for Saga
    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // In rating view, Saga should be HIDDEN from the pool at the bottom
    const poolList = screen.getByLabelText('Roll pool collection')
    expect(within(poolList).queryByText('Saga')).not.toBeInTheDocument()
    // Other threads (X-Men) should still be there
    expect(within(poolList).getByText('X-Men')).toBeInTheDocument()
  })

  it('[P4] refetches threads after successful rating', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const mockRefetchThreads = vi.fn()
    mockedUseThreads.mockReturnValue({
      data: [{ id: 1, title: 'Saga', format: 'Comics', status: 'active' }],
      refetch: mockRefetchThreads
    })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Submit rating
    await user.click(screen.getByText('Save & Continue'))

    // 3. Wait for ReviewForm modal to appear and click Skip
    await waitFor(() => {
      expect(screen.getByText('Write a Review?')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Skip'))

    // 4. Verify refetchThreads was called
    await waitFor(() => {
      expect(mockRefetchThreads).toHaveBeenCalled()
    })
  })

  it('[P5] closes rating view even if post-save refresh fails', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const refetchSessionError = new Error('session refresh failed')
    const mockRefetchSession = vi.fn().mockRejectedValue(refetchSessionError)
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: mockRefetchSession,
    })

    const mockRefetchThreads = vi.fn().mockRejectedValue(new Error('threads refresh failed'))
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
      ],
      refetch: mockRefetchThreads,
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))
    await user.click(screen.getByText('Save & Continue'))

    // Wait for ReviewForm modal to appear and click Skip
    await waitFor(() => {
      expect(screen.getByText('Write a Review?')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Skip'))

    await waitFor(() => {
      expect(screen.queryByText('How was it?')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Failed to save rating')).not.toBeInTheDocument()
  })

  it('[P5b] closes rating view when threads refresh fails after session refresh succeeds', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const mockRefetchSession = vi.fn().mockResolvedValue({})
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: mockRefetchSession,
    })

    const mockRefetchThreads = vi.fn().mockRejectedValue(new Error('threads refresh failed'))
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
      ],
      refetch: mockRefetchThreads,
    })

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))
    await user.click(screen.getByText('Save & Continue'))

    // Wait for ReviewForm modal to appear and click Skip
    await waitFor(() => {
      expect(screen.getByText('Write a Review?')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Skip'))

    await waitFor(() => {
      expect(screen.queryByText('How was it?')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Failed to save rating')).not.toBeInTheDocument()
    expect(mockRefetchSession).toHaveBeenCalled()
    expect(mockRefetchThreads).toHaveBeenCalled()
  })

  it('[P6] does not auto-finish session when rating the last issue', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      ...baseRollResponse,
      title: 'Final Issue Thread',
      issues_remaining: 1,
    })

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    // 2. Submit rating (Save & Complete when it's the last issue)
    await user.click(screen.getByText('Save & Complete'))

    // 3. Wait for ReviewForm modal to appear and click Skip
    await waitFor(() => {
      expect(screen.getByText('Write a Review?')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Skip'))

    // 4. Verify the UI never auto-finishes the session for the last issue.
    await waitFor(() => {
      expect(mockRate).toHaveBeenCalledWith(expect.objectContaining({
        rating: 3,
        finish_session: false
      }))
    })
  })

  it('[P7] does not show Save & Finish Session action', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue({
      ...baseRollResponse,
      title: 'Ongoing Thread',
    })

    const mockRate = vi.fn().mockResolvedValue({})
    mockedUseRate.mockReturnValue({ mutate: mockRate, isPending: false })

    const user = userEvent.setup()
    render(<RollPage />)

    // 1. Enter rating view
    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    expect(screen.queryByText('Save & Finish Session')).not.toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(mockRate).not.toHaveBeenCalled()
  })

  it('[P8] cancel clears rating view and roll-selection state', async () => {
    const { threadsApi } = await import('../services/api')
    vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)

    const user = userEvent.setup()
    render(<RollPage />)

    const sagaItem = getPoolItem('Saga')
    await user.click(sagaItem)
    await user.click(screen.getByText('Read Now'))

    await user.click(screen.getByText('Cancel Pending Roll'))

    expect(screen.getByText('Tap Die to Roll')).toBeInTheDocument()

    const selectedPoolItem = document.querySelector('.pool-thread-selected')
    expect(selectedPoolItem).toBeNull()
  })

  it('restores pending rating view from session state on load', async () => {
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 6,
        pending_thread_id: 1,
        manual_die: null,
        active_thread: {
          id: 1,
          title: 'Saga',
          format: 'Comics',
          issues_remaining: 5,
          queue_position: 2,
        },
      },
      refetch: vi.fn(),
    })

    render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('Saga')).toBeInTheDocument()
      expect(screen.getByText('Rolled 6 on d6')).toBeInTheDocument()
    })
  })

  it('hydrates pending thread metadata when active threads arrive after initial render', async () => {
    const sessionData = {
      current_die: 6,
      last_rolled_result: 5,
      pending_thread_id: 2,
      manual_die: null,
      active_thread: {
        id: 1,
        title: 'Saga',
        format: 'Comics',
        issues_remaining: 5,
        queue_position: 1,
      },
    }

    const refetchSessionSpy = vi.fn()
    const refetchThreadsSpy = vi.fn()
    let threadsData: MockThread[] = []

    mockedUseSession.mockImplementation(() => ({
      data: sessionData,
      refetch: refetchSessionSpy,
    }))
    mockedUseThreads.mockImplementation(() => ({
      data: threadsData,
      refetch: refetchThreadsSpy,
    }))

    const { rerender } = render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('Loading...')).toBeInTheDocument()
    })

    threadsData = [
      {
        id: 2,
        title: 'X-Men',
        format: 'Comics',
        issues_remaining: 7,
        queue_position: 3,
        status: 'active',
      },
    ]

    rerender(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('X-Men')).toBeInTheDocument()
    })
  })

  it('does not render invalid rolled zero text when pending roll result is missing', async () => {
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        pending_thread_id: 1,
        manual_die: null,
        active_thread: {
          id: 1,
          title: 'Saga',
          format: 'Comics',
          issues_remaining: 5,
          queue_position: 2,
        },
      },
      refetch: vi.fn(),
    })

    render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.queryByText('Rolled 0 on d6')).not.toBeInTheDocument()
    })
  })

  it('does not render invalid rolled zero text when pending roll result is zero', async () => {
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 0,
        pending_thread_id: 1,
        manual_die: null,
        active_thread: {
          id: 1,
          title: 'Saga',
          format: 'Comics',
          issues_remaining: 5,
          queue_position: 2,
        },
      },
      refetch: vi.fn(),
    })

    render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.queryByText('Rolled 0 on d6')).not.toBeInTheDocument()
    })
  })

  it('recovers from roll conflicts by refetching session and reopening rating view', async () => {
    const conflictError = {
      response: {
        status: 409,
        data: { detail: 'Pending roll already exists' },
      },
    }
    const mockRoll = vi.fn().mockRejectedValue(conflictError)
    const refetchSessionSpy = vi.fn().mockResolvedValue({
      current_die: 6,
      last_rolled_result: 5,
      pending_thread_id: 2,
      active_thread: {
        id: 2,
        title: 'X-Men',
        format: 'Comics',
        issues_remaining: 7,
        queue_position: 1,
      },
      snoozed_threads: [],
    })

    mockedUseRoll.mockReturnValue({ mutate: mockRoll, isPending: false })
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        pending_thread_id: null,
        snoozed_threads: [],
      },
      refetch: refetchSessionSpy,
    })
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active', queue_position: 1 },
        { id: 1, title: 'Saga', format: 'Comics', status: 'active', queue_position: 2 },
      ],
      refetch: vi.fn(),
    })

    const user = userEvent.setup()
    render(<RollPage />)

    await user.click(screen.getByLabelText('Roll the dice'))

    await waitFor(() => {
      expect(mockRoll).toHaveBeenCalled()
    }, { timeout: 2500 })
    await waitFor(() => {
      expect(refetchSessionSpy).toHaveBeenCalled()
    }, { timeout: 2500 })
    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
      expect(screen.getByText('X-Men')).toBeInTheDocument()
    })
  })

  it('renders current die in rating preview (not predicted)', async () => {
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 6,
        pending_thread_id: 1,
        manual_die: null,
        active_thread: {
          id: 1,
          title: 'Saga',
          format: 'Comics',
          issues_remaining: 5,
          queue_position: 2,
        },
      },
      refetch: vi.fn(),
    })

    render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
    })

    const previewContainer = document.getElementById('rating-preview-dice')
    const previewDie = within(previewContainer as HTMLElement).getByTestId('lazy-dice')
    expect(previewDie).toHaveAttribute('data-sides', '6')

    fireEvent.change(screen.getByLabelText(/rating/i), { target: { value: '1.0' } })

    expect(within(previewContainer as HTMLElement).getByTestId('lazy-dice')).toHaveAttribute('data-sides', '6')
  })

  it('cancels pending roll through dismiss mutation', async () => {
    const dismissSpy = vi.fn().mockResolvedValue({})
    const refetchSessionSpy = vi.fn().mockResolvedValue({})
    const refetchThreadsSpy = vi.fn().mockResolvedValue({})

    mockedUseDismissPending.mockReturnValue({ mutate: dismissSpy, isPending: false })
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: 2,
        pending_thread_id: 1,
        manual_die: null,
        active_thread: {
          id: 1,
          title: 'Saga',
          format: 'Comics',
          issues_remaining: 5,
          queue_position: 1,
        },
      },
      refetch: refetchSessionSpy,
    })
    mockedUseThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comics', status: 'active', queue_position: 1 },
        { id: 2, title: 'X-Men', format: 'Comics', status: 'active', queue_position: 2 },
      ],
      refetch: refetchThreadsSpy,
    })

    const user = userEvent.setup()
    render(<RollPage />)

    await waitFor(() => {
      expect(screen.getByText('How was it?')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Cancel Pending Roll'))

    await waitFor(() => {
      expect(dismissSpy).toHaveBeenCalled()
      expect(refetchSessionSpy).toHaveBeenCalled()
      expect(refetchThreadsSpy).toHaveBeenCalled()
    })
  })

  describe('Empty state', () => {
    it('shows empty state with "Nothing to roll yet" when no threads exist', async () => {
      mockedUseSession.mockReturnValue({
        data: {
          current_die: 6,
          last_rolled_result: null,
          manual_die: null,
          has_restore_point: false,
          snoozed_threads: [],
        },
        refetch: vi.fn(),
      })
      mockedUseThreads.mockReturnValue({
        data: [],
        refetch: vi.fn(),
      })
      mockedUseStaleThreads.mockReturnValue({ data: [] })

      render(<RollPage />)

      await waitFor(() => {
        expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
        expect(screen.getByText('Your reading queue is empty — add some comic threads to get started.')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: '+ Add a Thread' })).toBeInTheDocument()
        expect(screen.getByText('How it works:')).toBeInTheDocument()
      })
    })

    it('shows "All threads are blocked or snoozed" when threads exist but all blocked', async () => {
      mockedUseSession.mockReturnValue({
        data: {
          current_die: 6,
          last_rolled_result: null,
          manual_die: null,
          has_restore_point: false,
          snoozed_threads: [],
        },
        refetch: vi.fn(),
      })
      mockedUseThreads.mockReturnValue({
        data: [
          { id: 1, title: 'Saga', format: 'Comics', status: 'active', is_blocked: true },
        ],
        refetch: vi.fn(),
      })
      mockedUseStaleThreads.mockReturnValue({ data: [] })

      render(<RollPage />)

      await waitFor(() => {
        expect(screen.getByText('All threads are blocked or snoozed')).toBeInTheDocument()
        expect(screen.getByText('Check your queue to see what needs to be read to unlock more options.')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
      })
    })

    it('shows "All threads are blocked or snoozed" when threads exist but all snoozed', async () => {
      mockedUseSession.mockReturnValue({
        data: {
          current_die: 6,
          last_rolled_result: null,
          manual_die: null,
          has_restore_point: false,
          snoozed_threads: [
            { id: 1, title: 'Saga', format: 'Comics' },
            { id: 2, title: 'X-Men', format: 'Comics' },
          ],
        },
        refetch: vi.fn(),
      })
      mockedUseThreads.mockReturnValue({
        data: [],
        refetch: vi.fn(),
      })
      mockedUseStaleThreads.mockReturnValue({ data: [] })

      render(<RollPage />)

      await waitFor(() => {
        expect(screen.getByText('All threads are blocked or snoozed')).toBeInTheDocument()
        expect(screen.getByText('Check your queue to see what needs to be read to unlock more options.')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
      })
    })

    it('navigates to queue with openCreate when clicking "Add a Thread"', async () => {
      mockedUseSession.mockReturnValue({
        data: {
          current_die: 6,
          last_rolled_result: null,
          manual_die: null,
          has_restore_point: false,
          snoozed_threads: [],
        },
        refetch: vi.fn(),
      })
      mockedUseThreads.mockReturnValue({
        data: [],
        refetch: vi.fn(),
      })
      mockedUseStaleThreads.mockReturnValue({ data: [] })

      const user = userEvent.setup()
      render(<RollPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: '+ Add a Thread' })).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: '+ Add a Thread' }))

      expect(navigateSpy).toHaveBeenCalledWith('/queue', { state: { openCreate: true } })
    })

    it('navigates to queue when clicking "Go to Queue" in blocked/snoozed state', async () => {
      mockedUseSession.mockReturnValue({
        data: {
          current_die: 6,
          last_rolled_result: null,
          manual_die: null,
          has_restore_point: false,
          snoozed_threads: [
            { id: 1, title: 'Saga', format: 'Comics' },
          ],
        },
        refetch: vi.fn(),
      })
      mockedUseThreads.mockReturnValue({
        data: [],
        refetch: vi.fn(),
      })
      mockedUseStaleThreads.mockReturnValue({ data: [] })

      const user = userEvent.setup()
      render(<RollPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: 'Go to Queue' }))

      expect(navigateSpy).toHaveBeenCalledWith('/queue')
    })
  })
})
