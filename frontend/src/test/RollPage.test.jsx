import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useClearManualDie, useOverrideRoll, useRoll, useSetDie } from '../hooks/useRoll'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'

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

vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
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
  useMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
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
