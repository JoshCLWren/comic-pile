import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useClearManualDie, useOverrideRoll, useReroll, useSetDie } from '../hooks/useRoll'

vi.mock('../components/LazyDice3D', () => ({
  default: () => <div data-testid="lazy-dice" />,
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useStaleThreads: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useReroll: vi.fn(),
  useOverrideRoll: vi.fn(),
}))

beforeEach(() => {
  useSession.mockReturnValue({
    data: {
      current_die: 6,
      last_rolled_result: 2,
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
  useReroll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useOverrideRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
})

it('renders roll page content and opens override modal', async () => {
  const user = userEvent.setup()
  render(<RollPage />)

  expect(screen.getByText('Pile Roller')).toBeInTheDocument()
  expect(screen.getByText('Tap Die to Roll')).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /override/i }))
  expect(screen.getByText('Override Roll')).toBeInTheDocument()
})
