import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { computePredictedDie } from '../pages/RollPage/utils'

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
          readingOrders={[]}
          connectedThreads={[]}
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
    expect(computePredictedDie(undefined as unknown as number, 4.0)).toBe(4)
  })
})
