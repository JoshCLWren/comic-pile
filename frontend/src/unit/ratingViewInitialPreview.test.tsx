import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

// Mock heavy components
vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView({ currentDie, rating, predictedDie }: { currentDie: number; rating: number; predictedDie: number }) {
  return render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={{
          id: 1,
          title: 'Test',
          format: 'Comic',
          issues_remaining: 3,
          total_issues: 10,
          reading_progress: 'in_progress',
          issue_id: null,
          issue_number: '1',
          next_issue_id: null,
          next_issue_number: null,
          last_rolled_result: null,
        } as any}
        currentDie={currentDie}
        rolledResult={null}
        rating={rating}
        predictedDie={predictedDie}
        hasValidRolledResult={false}
        poolSize={0}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        {...callbacks}
      />
    </MemoryRouter>
  )
}

describe('RatingView initial preview', () => {
  it('shows correct die transition and direction for low rating', () => {
    renderRatingView({ currentDie: 20, rating: 3.0, predictedDie: 30 })
    expect(screen.getByText('d20 → d30')).toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
  })
})
