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
    readingOrdersIsLoading: false,
    readingOrdersError: null,
    connectedThreadsIsLoading: false,
    connectedThreadsError: null,
    onRequestReadingContext: vi.fn(),
    onRequestReadingBoundaries: vi.fn(),
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

function dependencyEdge(id: number): ReaderContextResponse['local_chain']['edges'][number] {
  return {
    id,
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
  }
}

describe('RatingView Reading Context and Reading Boundaries cards (#2764)', () => {
  it('renders both collapsed optional cards below the decision with no third disclosure', () => {
    const { container } = renderWithToast(ratingView())
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    // Collapsed: no expanded content and no loading skeleton for unrequested data.
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-content')).not.toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).toBeNull()
    // No redundant third entry point and no restored Why this?.
    expect(screen.queryByTestId('context-disclosure')).not.toBeInTheDocument()
    expect(screen.queryByText('Series history & crossovers')).not.toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    // Both cards live inside the decision region, not a peer middle column.
    const decisionRegion = container.querySelector('[data-testid="rating-region-decision"]')
    expect(decisionRegion).not.toBeNull()
    expect(decisionRegion!.contains(screen.getByTestId('reading-context-button'))).toBe(true)
    expect(decisionRegion!.contains(screen.getByTestId('reading-boundaries-button'))).toBe(true)
  })

  it('renders no lazy controls without an active rating thread', () => {
    renderWithToast(ratingView({ activeRatingThread: null }))
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('opening context requests only the context scope and reveals local content', async () => {
    const user = userEvent.setup()
    const onRequestReadingContext = vi.fn()
    const onRequestReadingBoundaries = vi.fn()
    renderWithToast(
      ratingView({
        readerContext: makeContext([dependencyEdge(1)], 'Saga'),
        readingContextRequested: true,
        onRequestReadingContext,
        onRequestReadingBoundaries,
      }),
    )

    await user.click(screen.getByTestId('reading-context-button'))
    expect(onRequestReadingContext).toHaveBeenCalledTimes(1)
    expect(onRequestReadingBoundaries).not.toHaveBeenCalled()
    expect(screen.getByTestId('reading-context-content')).toBeInTheDocument()
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-content')).not.toBeInTheDocument()
  })

  it('opening boundaries requests only the boundaries scope and reveals edge content', async () => {
    const user = userEvent.setup()
    const onRequestReadingContext = vi.fn()
    const onRequestReadingBoundaries = vi.fn()
    renderWithToast(
      ratingView({
        readerContext: makeContext([dependencyEdge(1)]),
        readingBoundariesRequested: true,
        onRequestReadingContext,
        onRequestReadingBoundaries,
      }),
    )

    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(onRequestReadingBoundaries).toHaveBeenCalledTimes(1)
    expect(onRequestReadingContext).not.toHaveBeenCalled()
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
    expect(screen.getByText('Your Reading Boundaries')).toBeInTheDocument()
    expect(screen.getByText('Dependency:')).toBeInTheDocument()
    expect(screen.getByText('Finish the previous issue first.')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
  })

  it('renders continuity-only boundaries without requiring dependency edges', async () => {
    const user = userEvent.setup()
    renderWithToast(
      ratingView({
        readerContext: makeContext([
          {
            id: 7,
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
        readingBoundariesRequested: true,
      }),
    )

    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
    expect(screen.getByText('Your Reading Boundaries')).toBeInTheDocument()
    expect(screen.getByText('Continuity:')).toBeInTheDocument()
    expect(screen.getByText('Crossover order')).toBeInTheDocument()
  })

  it('renders an honest empty state when no boundary edges exist', async () => {
    const user = userEvent.setup()
    renderWithToast(
      ratingView({
        readerContext: makeContext([], 'Saga'),
        readingBoundariesRequested: true,
      }),
    )

    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
    expect(
      screen.getByText('No prerequisite or continuity boundaries were found for this issue.'),
    ).toBeInTheDocument()
  })

  it('renders local loading state only after the scope is requested', async () => {
    const user = userEvent.setup()
    // Requested but still pending: the opened card shows the loading copy.
    renderWithToast(
      ratingView({ readingBoundariesRequested: true, isReaderContextLoading: true }),
    )
    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Checking reading context…')).toBeInTheDocument()
  })

  it('shows no skeleton for unrequested data even while the shared query is pending', () => {
    const { container } = renderWithToast(ratingView({ isReaderContextLoading: true }))
    expect(container.querySelector('.animate-pulse')).toBeNull()
    expect(screen.getByRole('slider')).toBeInTheDocument()
  })

  it('keeps the rating workflow usable when the optional request fails', async () => {
    const user = userEvent.setup()
    renderWithToast(
      ratingView({
        readingBoundariesRequested: true,
        readerContextError: new Error('reader context unavailable'),
      }),
    )

    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Local reading context unavailable')).toBeInTheDocument()
    expect(screen.getByText('reader context unavailable')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })

  it('supports both cards open at once without coupling their toggles', async () => {
    const user = userEvent.setup()
    renderWithToast(
      ratingView({
        readerContext: makeContext([dependencyEdge(1)], 'Saga'),
        readingContextRequested: true,
        readingBoundariesRequested: true,
      }),
    )

    await user.click(screen.getByTestId('reading-context-button'))
    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByTestId('reading-context-content')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()

    await user.click(screen.getByTestId('reading-context-button'))
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
  })

  it('reserves no middle-column region after restoration', () => {
    const { container } = renderWithToast(ratingView({
      readerContext: makeContext([], 'Saga'),
    }))
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
  })

  it('still renders comic and decision regions and rating actions', () => {
    renderWithToast(ratingView({ readerContext: makeContext([], 'Saga') }))
    expect(screen.getByTestId('rating-region-comic')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-decision')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })
})
