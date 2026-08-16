import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({
    readiness: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(activeRatingThread: Parameters<typeof RatingView>[0]['activeRatingThread']) {
  return render(
    <RatingView
      activeRatingThread={activeRatingThread}
      currentDie={6}
      rolledResult={activeRatingThread ? 3 : null}
      rating={4}
      predictedDie={4}
      hasValidRolledResult={Boolean(activeRatingThread)}
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

describe('RatingView issue #324 progress contract', () => {
  it('shows percentage complete and issues remaining', () => {
    renderRatingView({
      id: 1,
      title: 'X-Force',
      format: 'Comics',
      issues_remaining: 28,
      total_issues: 100,
      issue_number: '79',
      next_issue_number: '79',
    } as never)

    const info = screen.getByText('X-Force').closest('section')
    expect(info).toBeInTheDocument()
    expect(info).toHaveTextContent('72% complete')
    expect(info).toHaveTextContent('28 issues left')
  })

  it('shows 0% complete for an unread thread', () => {
    renderRatingView({
      id: 2,
      title: 'Unread Thread',
      format: 'Comics',
      issues_remaining: 10,
      total_issues: 10,
      issue_number: '1',
      next_issue_number: '1',
    } as never)

    const info = screen.getByText('Unread Thread').closest('section')
    expect(info).toHaveTextContent('0% complete')
    expect(info).toHaveTextContent('10 issues left')
  })

  it('shows 100% complete and 0 issues left for a completed thread', () => {
    renderRatingView({
      id: 3,
      title: 'Completed Thread',
      format: 'Comics',
      issues_remaining: 0,
      total_issues: 10,
      issue_number: null,
      next_issue_number: null,
      reading_progress: 'completed',
    } as never)

    const info = screen.getByText('Completed Thread').closest('section')
    expect(info).toHaveTextContent('100% complete')
    expect(info).toHaveTextContent('0 issues left')
  })

  it('uses singular wording for exactly one issue remaining', () => {
    renderRatingView({
      id: 4,
      title: 'Last Issue Thread',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 10,
      issue_number: '10',
      next_issue_number: '10',
    } as never)

    const info = screen.getByText('Last Issue Thread').closest('section')
    expect(info).toHaveTextContent('1 issue left')
  })
})
