import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'
import { createRouterHarness } from './routerTestHarness'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { RatingViewData } from '../pages/RollPage/useRatingView'

const toast = createToastSpy()

function ToastWrapper({ children }: { children: ReactNode }) {
  return <ToastContextSpy value={toast}>{children}</ToastContextSpy>
}

function renderWithToast(ui: ReactElement) {
  return render(ui, { wrapper: ToastWrapper })
}

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
    manualDie: null,
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
    readingContextRequested: false,
    readingBoundariesRequested: false,
    readingOrders: [],
    connectedThreads: [],
    onShowContext: vi.fn(),
    onShowBoundaries: vi.fn(),
    readingOrdersIsLoading: false,
    readingOrdersError: null,
    connectedThreadsIsLoading: false,
    connectedThreadsError: null,
    ...overrides,
  }
}

function renderRatingView(overrides: Partial<RatingViewData> = {}) {
  const { wrapper: RouterWrapper } = createRouterHarness();
  return renderWithToast(
    <RouterWrapper>
      <RatingView data={makeRatingViewData(overrides)} />
    </RouterWrapper>,
  )
}

describe('RatingView crossovers behind the optional context card (#2764)', () => {
  it('keeps crossover chrome collapsed behind Show context until it is opened', () => {
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

    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
    expect(screen.queryByText('Cosmic bridge')).not.toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
  })

  it('does not show crossover chrome without an active thread', () => {
    renderRatingView({ activeRatingThread: null })

    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
  })
})
