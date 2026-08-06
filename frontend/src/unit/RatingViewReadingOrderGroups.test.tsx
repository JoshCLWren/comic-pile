import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../hooks/useDependencyGroups', () => ({
  useDependencyGroups: (threadId: number | null | undefined) => ({
    groups: threadId === 42 ? [{ id: 7, name: 'Cosmic bridge' }] : [],
    isLoading: false,
    error: null,
  }),
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

describe('RatingView crossovers', () => {
  it('shows crossover names owned by the active rating thread', () => {
    render(
      <RatingView
        activeRatingThread={{
          id: 42,
          title: 'Silver Surfer',
          format: 'Comic',
          issues_remaining: 3,
          total_issues: 6,
          issue_number: '3',
          next_issue_number: '4',
        } as never}
        currentDie={6}
        rolledResult={3}
        rating={4}
        predictedDie={4}
        hasValidRolledResult
        poolSize={6}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        {...callbacks}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Crossovers' })).toBeInTheDocument()
    expect(screen.getByText('Cosmic bridge')).toBeInTheDocument()
  })

  it('does not show crossover chrome without an active thread', () => {
    render(
      <RatingView
        activeRatingThread={null}
        currentDie={6}
        rolledResult={null}
        rating={3}
        predictedDie={6}
        hasValidRolledResult={false}
        poolSize={0}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        {...callbacks}
      />,
    )

    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
  })
})
