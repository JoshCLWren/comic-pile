import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread } from '../types/rollBootstrap'

const navigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-router-dom')>(),
  useNavigate: () => navigate,
}))

type PoolProps = Parameters<typeof ThreadPool>[0]

const baseProps: PoolProps = {
  pool: [],
  dieSize: 6,
  isRatingView: false,
  selectedThreadId: null,
  snoozedThreads: [],
  snoozedExpanded: false,
  onThreadClick: vi.fn(),
  onUnsnooze: vi.fn(),
  onToggleSnoozed: vi.fn(),
  onShuffle: vi.fn(),
  unsnoozeIsPending: false,
  shuffleIsPending: false,
}

function mount(overrides: Partial<PoolProps> = {}) {
  return render(
    <MemoryRouter>
      <ThreadPool {...baseProps} {...overrides} />
    </MemoryRouter>,
  )
}

describe('ThreadPool empty-pool branch coverage', () => {
  it('navigates to the queue from the blocked branch', () => {
    navigate.mockClear()
    mount({ pool: [], emptyPoolReason: 'all_blocked' })
    fireEvent.click(screen.getByRole('button', { name: 'Go to Queue' }))
    expect(navigate).toHaveBeenCalledWith('/queue')
  })

  it('opens create from the completed branch', () => {
    navigate.mockClear()
    mount({ pool: [], emptyPoolReason: 'all_completed' })
    fireEvent.click(screen.getByRole('button', { name: '+ Add a Series' }))
    expect(navigate).toHaveBeenCalledWith('/queue', { state: { openCreate: true } })
  })

  it('navigates to the queue from the out-of-pool branch', () => {
    navigate.mockClear()
    mount({ pool: [], emptyPoolReason: 'all_out_of_pool' })
    fireEvent.click(screen.getByRole('button', { name: 'Go to Queue' }))
    expect(navigate).toHaveBeenCalledWith('/queue')
  })

  it('opens create and navigates to the queue from the zero-choice branch', () => {
    navigate.mockClear()
    mount({
      pool: [],
      snoozedThreads: [{ id: 2, title: 'Paused', format: 'Comic' }],
      onResetDice: vi.fn(),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add Comics' }))
    expect(navigate).toHaveBeenCalledWith('/queue', { state: { openCreate: true } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to Queue' }))
    expect(navigate).toHaveBeenCalledWith('/queue')
  })

  it('reconciles browser snoozes with a no_series reason to show reset', () => {
    const onResetDice = vi.fn()
    mount({
      pool: [],
      emptyPoolReason: 'no_series',
      snoozedThreads: [],
      snoozedCount: 0,
      browserSnoozedThreadIds: [1],
      onResetDice,
    })
    expect(screen.getByText('Every series is snoozed')).toBeInTheDocument()
    expect(screen.getByTestId('reset-dice-zero-choice')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('reset-dice-zero-choice'))
    expect(onResetDice).toHaveBeenCalledTimes(1)
  })
})
