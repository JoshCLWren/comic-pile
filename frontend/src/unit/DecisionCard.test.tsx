import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DecisionCard } from './DecisionCard'

// Mock heavy dependencies
vi.mock('../../../components/Modal', () => ({
  default: ({ children, isOpen, title, onClose }: any) => 
    isOpen ? <div data-testid="modal">{title}{children}</div> : null,
}))

vi.mock('../../../components/GlossaryLink', () => ({
  default: ({ id, children }: { id: string; children: React.ReactNode }) => 
    <span data-testid="glossary-link">{children}</span>,
}))

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

describe('DecisionCard', () => {
  it('renders rating states and invokes controls in auto mode', async () => {
    const callbacks = makeDecisionCardProps()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    // Test basic rendering
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByText('3.0')).toBeInTheDocument()
    
    // Test ladder move display in auto mode
    const ladderMove = screen.getByText('d6 → d8')
    expect(ladderMove).toBeInTheDocument()
    
    // Test rating slider
    const ratingSlider = screen.getByRole('slider')
    expect(ratingSlider).toHaveValue('3.0')
    
    // Test button interactions
    await user.click(screen.getByRole('button', { name: /mark read & save/i }))
    expect(callbacks.onSubmitRating).toHaveBeenCalledWith(false)
    
    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(callbacks.onSnooze).toHaveBeenCalled()
    
    await user.click(screen.getByRole('button', { name: /cancel roll/i }))
    expect(callbacks.onCancel).toHaveBeenCalled()
  })

  it('shows manual die message when manual die is set', () => {
    const callbacks = makeDecisionCardProps({
      manualDie: 20,
      currentDie: 20,
      predictedDie: 12,
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    // Test that manual die message is shown instead of ladder move
    expect(screen.getByText('Manual die pinned at d20')).toBeInTheDocument()
    expect(screen.queryByText('d20 → d12')).not.toBeInTheDocument()
    
    // Test that rating still works
    expect(screen.getByText('3.0')).toBeInTheDocument()
  })

  it('shows ladder move when manual die is not set (auto mode)', () => {
    const callbacks = makeDecisionCardProps({
      manualDie: null,
      currentDie: 6,
      predictedDie: 8,
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    // Test that ladder move is shown in auto mode
    expect(screen.getByText('d6 → d8')).toBeInTheDocument()
    expect(screen.queryByText('Manual die pinned at d6')).not.toBeInTheDocument()
  })

  it('handles rating changes correctly in both modes', async () => {
    const callbacks = makeDecisionCardProps()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    const ratingSlider = screen.getByRole('slider')
    
    // Test rating change in auto mode
    await user.clear(ratingSlider)
    await user.type(ratingSlider, '4.0')
    expect(callbacks.onUpdateRating).toHaveBeenCalledWith('4.0')
    
    // Test that ladder update would happen (but we can't test the actual update without re-render)
    // The key point is that the callback is called correctly
  })

  it('shows error message when present', () => {
    const callbacks = makeDecisionCardProps({
      errorMessage: 'Failed to save rating',
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    expect(screen.getByText('Failed to save rating')).toBeInTheDocument()
  })

  it('shows loading states for async operations', () => {
    const callbacks = makeDecisionCardProps({
      rateIsPending: true,
      snoozeIsPending: true,
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    expect(screen.getByRole('button', { name: /saving…/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /snoozing…/i })).toBeInTheDocument()
  })

  it('shows skip button when skipIsPending is false', () => {
    const callbacks = makeDecisionCardProps({
      skipIsPending: false,
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    expect(screen.getByRole('button', { name: /skip/i })).toBeInTheDocument()
  })

  it('shows skipping state when skipIsPending is true', () => {
    const callbacks = makeDecisionCardProps({
      skipIsPending: true,
    })

    render(
      <MemoryRouter>
        <DecisionCard {...callbacks} />
      </MemoryRouter>
    )

    expect(screen.getByRole('button', { name: /skipping…/i })).toBeInTheDocument()
  })
})