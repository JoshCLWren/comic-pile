import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

vi.mock('../components/LazyDice3D', () => ({ default: () => null }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({ readiness: null, isLoading: false, error: null, refetch: vi.fn() }),
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(issuesRemaining: number) {
  render(
    <RatingView
      activeRatingThread={{
        id: 1,
        title: 'Ultimate X-Men',
        format: 'Comic',
        issues_remaining: issuesRemaining,
        total_issues: 12,
        issue_number: '11',
        next_issue_number: '12',
      } as never}
      currentDie={6}
      rolledResult={2}
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
}

describe('RatingView submit button label', () => {
  it('reads "Mark read & complete" when rating the last remaining issue', () => {
    renderRatingView(1)
    const submitButton = screen.getByTestId('save-and-continue')
    expect(submitButton).toHaveTextContent('Mark read & complete')
    expect(submitButton).not.toHaveTextContent('Mark read & save')
  })

  it('reads "Mark read & save" when multiple issues remain', () => {
    renderRatingView(5)
    const submitButton = screen.getByTestId('save-and-continue')
    expect(submitButton).toHaveTextContent('Mark read & save')
    expect(submitButton).not.toHaveTextContent('Mark read & complete')
  })
})
