import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

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
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () => ({
    data: null,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('../hooks/useReaderContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useReaderContext')>()
  return {
    ...actual,
    useReaderContext: () => ({
      context: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }),
  }
})

function makeRatingViewData(overrides: Partial<RatingViewData> = {}): RatingViewData {
  return {
    activeRatingThread: {
      id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_number: '3',
      next_issue_number: '4',
      reading_progress: 'in_progress',
      queue_position: 0,
      issue_id: 100,
      next_issue_id: 101,
    },
    currentDie: 6,
    rolledResult: 3,
    rating: 4,
    predictedDie: 4,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    skipIsPending: false,
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onSkip: undefined,
    onCancel: vi.fn(),
    onRefreshThread: vi.fn(),
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ratingViewTopRef: null,
    issuesRemaining: 5,
    ...overrides,
  }
}

function renderRatingView(overrides: Partial<RatingViewData> = {}) {
  return render(
    <MemoryRouter>
      <RatingView data={makeRatingViewData(overrides)} />
    </MemoryRouter>,
  )
}

describe('RatingView crossovers retired from rating screen (#2711)', () => {
  it('does not show Reading Context button even when active thread would have owned crossovers', () => {
    renderRatingView({
      activeRatingThread: {
        id: 42,
        title: 'Silver Surfer',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 6,
        issue_number: '3',
        next_issue_number: '4',
        reading_progress: 'in_progress',
        queue_position: 0,
        issue_id: 100,
        next_issue_id: 101,
      },
    })

    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
    expect(screen.queryByText('Cosmic bridge')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('does not show crossover chrome without an active thread', () => {
    renderRatingView({ activeRatingThread: null })

    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
  })
})
