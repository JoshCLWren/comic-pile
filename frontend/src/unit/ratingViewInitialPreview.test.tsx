import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { computePredictedDie } from '../pages/RollPage/utils'
import { cast } from '../utils/cast'

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
      <ToastProvider>
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
          errorMessage=""
          rateIsPending={false}
          snoozeIsPending={false}
          dismissIsPending={false}
          {...callbacks}
        />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe('RatingView initial preview', () => {
  it('shows correct die transition and direction for low rating', () => {
    renderRatingView({ currentDie: 20, rating: 3.0, predictedDie: 30 })
    expect(screen.getByText('d20 → d30')).toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
  })

  it('shows the d8 → d10 projection for a d8 current die at default rating 3.0', () => {
    renderRatingView({ currentDie: 8, rating: 3.0, predictedDie: computePredictedDie(8, 3.0) })
    expect(screen.getByText('d8 → d10')).toBeInTheDocument()
    expect(screen.queryByText('d8 → d8')).not.toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
  })

  it('renders the d6 → d8 projection for a second die rung at default rating 3.0', () => {
    renderRatingView({ currentDie: 6, rating: 3.0, predictedDie: computePredictedDie(6, 3.0) })
    expect(screen.getByText('d6 → d8')).toBeInTheDocument()
    expect(screen.queryByText('d6 → d6')).not.toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
  })

  it('computePredictedDie steps up for resume path at default rating 3.0 with d20', () => {
    expect(computePredictedDie(20, 3.0)).toBe(30)
  })

  it('computePredictedDie steps down for high rating', () => {
    expect(computePredictedDie(20, 4.0)).toBe(12)
    expect(computePredictedDie(20, 5.0)).toBe(12)
  })

  it('computePredictedDie handles boundaries', () => {
    expect(computePredictedDie(4, 3.0)).toBe(6)
    expect(computePredictedDie(100, 4.0)).toBe(50)
    expect(computePredictedDie(100, 3.0)).toBe(100)
  })

  it('computePredictedDie falls back to 6 when currentDie is falsy', () => {
    expect(computePredictedDie(0, 3.0)).toBe(8)
    expect(computePredictedDie(cast<number>(undefined), 4.0)).toBe(4)
  })
})
