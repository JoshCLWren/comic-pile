import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useClearManualDie, useOverrideRoll, useRoll, useSetDie } from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'

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

beforeEach(() => {
  useSession.mockReturnValue({
    data: {
      current_die: 6,
      last_rolled_result: null,
      manual_die: null,
      has_restore_point: false,
    },
  })
  useThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comic', status: 'active' },
      { id: 2, title: 'X-Men', format: 'Comic', status: 'active' },
    ],
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    await user.click(sagaPoolItem)

    const unsnoozeButton = screen.getByText('Unsnooze')
    await user.click(unsnoozeButton)

    expect(mockUnsnoozeMutation.mutate).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('navigates to /queue with editThreadId state when edit action is clicked', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
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

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    sagaPoolItem.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })

  it('opens action sheet when pressing Space on pool item', async () => {
    const user = userEvent.setup()
    render(<RollPage />)

    const sagaPoolItem = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    sagaPoolItem.focus()
    await user.keyboard(' ')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })
})
