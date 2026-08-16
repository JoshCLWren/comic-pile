import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { Thread } from '../types'

vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () => ({ data: null, isPending: false, isError: false, error: null }),
}))

const baseCallbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(threadOverrides: Partial<Thread> = {}) {
  const thread = {
    id: 1,
    title: 'Test Thread',
    format: 'Comic',
    issues_remaining: 10,
    total_issues: 10,
    next_issue_number: '1',
    issue_number: '1',
    ...threadOverrides,
  } as Thread

  return render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={thread}
        currentDie={6}
        rolledResult={3}
        rating={3}
        predictedDie={6}
        hasValidRolledResult
        poolSize={6}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        {...baseCallbacks}
      />
    </MemoryRouter>,
  )
}

describe('RatingView progress text (issue #324 / #1289)', () => {
  it('displays "72% complete" and "28 issues left" for a partially-read thread', () => {
    renderRatingView({ issues_remaining: 28, total_issues: 100 })

    expect(screen.getByText('72% complete')).toBeInTheDocument()
    expect(screen.getByText('28 issues left')).toBeInTheDocument()
  })

  it('displays "0% complete" and "10 issues left" for an unread thread', () => {
    renderRatingView({ issues_remaining: 10, total_issues: 10 })

    expect(screen.getByText('0% complete')).toBeInTheDocument()
    expect(screen.getByText('10 issues left')).toBeInTheDocument()
  })

  it('displays "100% complete" and "0 issues left" for a completed thread', () => {
    renderRatingView({ issues_remaining: 0, total_issues: 10 })

    expect(screen.getByText('100% complete')).toBeInTheDocument()
    expect(screen.getByText('0 issues left')).toBeInTheDocument()
  })

  it('displays singular "1 issue left" for a thread with one remaining', () => {
    renderRatingView({ issues_remaining: 1, total_issues: 10 })

    expect(screen.getByText('90% complete')).toBeInTheDocument()
    expect(screen.getByText('1 issue left')).toBeInTheDocument()
  })
})
