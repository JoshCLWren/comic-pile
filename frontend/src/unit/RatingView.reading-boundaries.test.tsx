import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'
import { createRouterHarness } from './routerTestHarness'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
import type { ReaderContextResponse } from '../types'

const toast = createToastSpy()

function ToastWrapper({ children }: { children: ReactNode }) {
  return <ToastContextSpy value={toast}>{children}</ToastContextSpy>
}

function renderWithToast(ui: ReactElement) {
  return render(ui, { wrapper: ToastWrapper })
}


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

function ratingView(overrides: Partial<RatingViewData> = {}) {
  const { wrapper: RouterWrapper } = createRouterHarness();
  return (
    <RouterWrapper>
      <RatingView data={makeRatingViewData(overrides)} />
    </RouterWrapper>
  )
}

function makeContext(edges: ReaderContextResponse['local_chain']['edges'], seriesName: string | null = null): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: seriesName ? 'comicvine' : 'unavailable',
      canonical_series_id: seriesName ? 'series-1' : null,
      series_name: seriesName,
      average_rating: seriesName ? 4.2 : null,
      ratings_count: seriesName ? 12 : 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: seriesName ? 5 : null,
      lowest_rating: seriesName ? 2 : null,
    },
    crossovers: [],
    local_chain: {
      issues: [
        { issue_id: 100, issue_number: '3', position: 1, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
      ],
      edges,
    },
  }
}

describe('RatingView Reading Boundaries optional card (#2764 restores #2519 behavior)', () => {
  it('renders collapsed Reading Context and Reading Boundaries cards with an active rating thread', () => {
    renderWithToast(ratingView())
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-content')).not.toBeInTheDocument()
  })

  it('renders no optional cards without an active rating thread', () => {
    renderWithToast(ratingView({ activeRatingThread: null }))
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('requests only boundaries when Show boundaries is pressed', async () => {
    const user = userEvent.setup()
    const onShowContext = vi.fn()
    const onShowBoundaries = vi.fn()
    renderWithToast(ratingView({ onShowContext, onShowBoundaries }))
    await user.click(screen.getByRole('button', { name: /show boundaries/i }))
    expect(onShowBoundaries).toHaveBeenCalledTimes(1)
    expect(onShowContext).not.toHaveBeenCalled()
  })

  it('renders prerequisite edges from exact reader-context data when boundaries are open', () => {
    renderWithToast(ratingView({
      readingBoundariesRequested: true,
      readerContext: makeContext([
        {
          id: 1,
          kind: 'dependency',
          source_issue_id: 98,
          target_issue_id: 100,
          source_thread_id: null,
          target_thread_id: null,
          source_label: '#2',
          target_label: '#3',
          source_status: 'read',
          target_status: 'unread',
          note: null,
          explanation: 'Finish the previous issue first.',
        },
      ]),
    }))
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
    expect(screen.getByText('Before this issue')).toBeInTheDocument()
    expect(screen.getByText('Finish the previous issue first.')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
  })

  it('renders a truthful empty note when no boundary edges exist', () => {
    renderWithToast(ratingView({
      readingBoundariesRequested: true,
      readerContext: makeContext([], 'Saga'),
    }))
    expect(
      screen.getByText('No prerequisites or continuity boundaries are recorded for this issue.'),
    ).toBeInTheDocument()
  })

  it('reserves no middle-column region for the optional cards', () => {
    const { container } = renderWithToast(ratingView({
      readingBoundariesRequested: true,
      readerContext: makeContext([], 'Saga'),
    }))
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    const cells = Array.from(grid!.querySelectorAll<HTMLElement>(':scope > div'))
    expect(cells.length).toBe(2)
  })

  it('keeps Why this? absent while the boundaries card is available', () => {
    renderWithToast(ratingView({
      readingBoundariesRequested: true,
      readerContext: makeContext([
        {
          id: 1,
          kind: 'continuity',
          source_issue_id: 99,
          target_issue_id: 100,
          source_thread_id: 52,
          target_thread_id: 53,
          source_label: null,
          target_label: null,
          source_status: 'read',
          target_status: 'unread',
          note: 'Crossover order',
          explanation: null,
        },
      ]),
    }))
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByText('Crossover order')).toBeInTheDocument()
  })

  it('still renders comic and decision regions and rating actions', () => {
    renderWithToast(ratingView({
      readingBoundariesRequested: true,
      readerContext: makeContext([], 'Saga'),
    }))
    expect(screen.getByTestId('rating-region-comic')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-decision')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })
})
