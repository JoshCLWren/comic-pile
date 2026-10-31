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
    snoozeIsPending: false,
    dismissIsPending: false,
    skipIsPending: false,
    manualDie: null,
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onSkip: vi.fn(),
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
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending?: boolean
  manualDie: number | null
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
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

    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(callbacks.onSnooze).toHaveBeenCalled()

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
      snoozeIsPending: true,
    })

    renderDecisionCard(callbacks)

    expect(screen.getByRole('button', { name: /saving…/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /snoozing…/i })).toBeInTheDocument()
  })

  it('shows skip button when skipIsPending is false', () => {
    const callbacks = makeDecisionCardProps({
      skipIsPending: false,
    })

    renderDecisionCard(callbacks)

    expect(screen.getByRole('button', { name: /skip/i })).toBeInTheDocument()
  })

  it('shows skipping state when skipIsPending is true', () => {
    const callbacks = makeDecisionCardProps({
      skipIsPending: true,
    })

    renderDecisionCard(callbacks)

    expect(screen.getByTestId('skip-roll')).toHaveTextContent('Skipping…')
  })
})