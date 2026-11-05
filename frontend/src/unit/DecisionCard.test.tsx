import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DecisionCard } from '../pages/RollPage/components/DecisionCard'

function makeDecisionCardProps(overrides: Partial<DecisionCardProps> = {}) {
  return {
    activeRatingThread: {
      id: 1,
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 3,
      queue_position: 1,
      total_issues: null,
      reading_progress: null,
      issue_id: null,
      issue_number: null,
      next_issue_id: null,
      next_issue_number: null,
      last_rolled_result: null,
    },
    currentDie: 6,
    rating: 3.0,
    predictedDie: 8,
    errorMessage: '',
    rateIsPending: false,
    rerollIsPending: false,
    dismissIsPending: false,
    manualDie: null,
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onReroll: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    ...overrides,
  }
}

interface DecisionCardProps {
  activeRatingThread: any
  currentDie: number
  rating: number
  predictedDie: number
  errorMessage: string
  rateIsPending: boolean
  rerollIsPending?: boolean
  dismissIsPending: boolean
  manualDie: number | null
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onReroll?: () => Promise<void>
  onResetDice?: () => void
  onCancel: () => void
}

function renderDecisionCard(props: DecisionCardProps): void {
  render(
    <MemoryRouter>
      <DecisionCard {...props} />
    </MemoryRouter>,
  )
}

function ratingReadout(): HTMLElement {
  return screen.getByTestId('decision-card')
}

describe('DecisionCard', () => {
  it('offers an explicit reset after the eligible library is exhausted', async () => {
    const onResetDice = vi.fn()
    renderDecisionCard(makeDecisionCardProps({
      errorMessage: 'No other eligible comics remain. Reset Dice to clear temporary snoozes, or wait until tomorrow.',
      onResetDice,
    }))
    expect(onResetDice).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reset Dice' }))
    expect(onResetDice).toHaveBeenCalledTimes(1)
  })

  it('invokes the Rust reroll action from the rating view', async () => {
    const onReroll = vi.fn().mockResolvedValue(undefined)
    renderDecisionCard(makeDecisionCardProps({ onReroll }))

    await userEvent.setup().click(screen.getByTestId('reroll-offer'))

    expect(onReroll).toHaveBeenCalledTimes(1)
  })

  it('renders rating states and invokes controls in automatic mode', async () => {
    const callbacks = makeDecisionCardProps()
    const user = userEvent.setup()

    renderDecisionCard(callbacks)

    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByText('3.0')).toBeInTheDocument()

    // Automatic mode keeps the ladder move readout and its glossary link.
    expect(ratingReadout().textContent).toContain('d6 → d8')

    const ratingSlider = screen.getByRole('slider')
    expect(ratingSlider).toHaveValue('3')

    await user.click(screen.getByRole('button', { name: /mark read & save/i }))
    expect(callbacks.onSubmitRating).toHaveBeenCalledWith(false)

    await user.click(screen.getByRole('button', { name: /roll again/i }))
    expect(callbacks.onReroll).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /cancel roll/i }))
    expect(callbacks.onCancel).toHaveBeenCalled()
  })

  // Issue #3144: manual mode pins the die, so the ladder move the card used to
  // promise never happens and the readout must stop advertising one.
  it('reports the pinned die instead of a ladder move in manual die mode', () => {
    const callbacks = makeDecisionCardProps({
      manualDie: 20,
      currentDie: 20,
      predictedDie: 12,
    })

    renderDecisionCard(callbacks)

    expect(ratingReadout().textContent).toContain('Manual mode is active at d20')
    expect(ratingReadout().textContent).not.toContain('→')
    expect(ratingReadout().textContent).not.toContain('d12')
    expect(screen.getByText('3.0')).toBeInTheDocument()
  })

  it('keeps the ladder move when no die is pinned', () => {
    const callbacks = makeDecisionCardProps({
      manualDie: null,
      currentDie: 6,
      predictedDie: 8,
    })

    renderDecisionCard(callbacks)

    expect(ratingReadout().textContent).toContain('d6 → d8')
    expect(ratingReadout().textContent).not.toContain('Manual mode is active')
  })

  it('forwards rating changes', () => {
    const callbacks = makeDecisionCardProps()

    renderDecisionCard(callbacks)

    fireEvent.change(screen.getByRole('slider'), { target: { value: '4.0' } })
    expect(callbacks.onUpdateRating).toHaveBeenCalledWith('4.0')
  })

  it('shows error message when present', () => {
    const callbacks = makeDecisionCardProps({
      errorMessage: 'Failed to save rating',
    })

    renderDecisionCard(callbacks)

    expect(screen.getByText('Failed to save rating')).toBeInTheDocument()
  })

  it('shows loading states for async operations', () => {
    const callbacks = makeDecisionCardProps({
      rateIsPending: true,
      rerollIsPending: true,
    })

    renderDecisionCard(callbacks)

    expect(screen.getByRole('button', { name: /saving…/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /rolling…/i })).toBeInTheDocument()
  })

  it('never renders a skip control: reroll is the only move-past action', () => {
    const callbacks = makeDecisionCardProps()

    renderDecisionCard(callbacks)

    expect(screen.queryByTestId('skip-roll')).not.toBeInTheDocument()
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('reroll-offer')).toBeInTheDocument()
  })
})