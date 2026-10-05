import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { ToastProvider } from '../contexts/ToastProvider'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
import type { ReaderContextResponse } from '../types'
import type { ReadingOrder } from '../services/api-reading-orders'

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
  return (
    <MemoryRouter>
      <ToastProvider>
        <RatingView data={makeRatingViewData(overrides)} />
      </ToastProvider>
    </MemoryRouter>
  )
}

function populatedContext(): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'series-1',
      series_name: 'Saga',
      average_rating: 4.2,
      ratings_count: 12,
      previous_issue: { issue_id: 99, issue_number: '2', rating: 4.0 },
      recent_ratings: [{ issue_id: 99, issue_number: '2', rating: 4.0 }],
      highest_rating: 5.0,
      lowest_rating: 2.0,
    },
    crossovers: [
      {
        id: 500,
        name: 'StoryArc 1',
        applies_to_current_issue: true,
        membership_kind: 'issue',
        next_member: null,
        average_rating: 4.0,
        ratings_count: 3,
        read_count: 2,
      },
    ],
    local_chain: {
      issues: [
        { issue_id: 99, issue_number: '2', position: 1, status: 'read', relation: 'previous', rating: 4.0, crossover_memberships: [] },
        { issue_id: 100, issue_number: '3', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [{ id: 500, name: 'StoryArc 1' }] },
        { issue_id: 101, issue_number: '4', position: 3, status: 'unread', relation: 'next', rating: null, crossover_memberships: [] },
      ],
      edges: [
        {
          id: 1,
          kind: 'dependency',
          source_issue_id: 99,
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
        {
          id: 2,
          kind: 'continuity',
          source_issue_id: 100,
          target_issue_id: 101,
          source_thread_id: null,
          target_thread_id: null,
          source_label: '#3',
          target_label: '#4',
          source_status: 'unread',
          target_status: 'unread',
          note: 'Continues directly.',
          explanation: null,
        },
      ],
    },
  }
}

function readingOrdersFixture(): ReadingOrder[] {
  return [
    { id: 7, name: 'Secret Wars Path', description: null, total_items: 4, completed_items: 1, items: [] },
  ]
}

describe('Roll optional reading cards collapsed state (#2764)', () => {
  it('renders separate Reading Context and Reading Boundaries cards below the decision', () => {
    const { container } = render(ratingView())
    expect(screen.getByTestId('reading-context-card')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-card')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show context/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show boundaries/i })).toBeInTheDocument()

    const decisionRegion = container.querySelector('[data-testid="rating-region-decision"]')
    expect(decisionRegion).not.toBeNull()
    expect(decisionRegion!.contains(screen.getByTestId('decision-card'))).toBe(true)
    expect(decisionRegion!.contains(screen.getByTestId('rating-region-reading-optional'))).toBe(true)
    const decisionText = decisionRegion!.textContent ?? ''
    expect(decisionText.indexOf('Your rating')).toBeLessThan(decisionText.indexOf('Reading Context'))
  })

  it('renders truthful collapsed copy with no settings implication', () => {
    render(ratingView())
    expect(
      screen.getByText('See how this issue fits into your reading plans and continuity.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Review recorded prerequisites and continuity edges around this issue.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/preference|settings/i)).not.toBeInTheDocument()
  })

  it('renders no loading skeleton for unrequested data', () => {
    const { container } = render(ratingView({ readerContext: populatedContext() }))
    expect(screen.queryByTestId('reading-context-loading')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-loading')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-content')).not.toBeInTheDocument()
    expect(container.querySelector('[data-testid="rating-region-reading-optional"] .animate-pulse')).toBeNull()
  })

  it('creates no middle peer column and keeps Why this? and the generic disclosure absent', () => {
    const { container } = render(ratingView({ readerContext: populatedContext() }))
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    const cells = Array.from(grid!.querySelectorAll<HTMLElement>(':scope > div'))
    expect(cells.length).toBe(2)
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByText('Series history & crossovers')).not.toBeInTheDocument()
    expect(screen.queryByTestId('context-disclosure')).not.toBeInTheDocument()
  })

  it('renders no cards without an active rating thread', () => {
    render(ratingView({ activeRatingThread: null }))
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })
})

describe('Roll optional reading cards interaction (#2764)', () => {
  it('Show context requests only context and reveals series and reading-plan content', async () => {
    const user = userEvent.setup()
    const onShowContext = vi.fn()
    const onShowBoundaries = vi.fn()
    const { rerender } = render(
      ratingView({ onShowContext, onShowBoundaries }),
    )

    await user.click(screen.getByRole('button', { name: /show context/i }))
    expect(onShowContext).toHaveBeenCalledTimes(1)
    expect(onShowBoundaries).not.toHaveBeenCalled()

    rerender(
      ratingView({
        onShowContext,
        onShowBoundaries,
        readingContextRequested: true,
        readerContext: populatedContext(),
        readingOrders: readingOrdersFixture(),
      }),
    )
    expect(screen.getByTestId('reading-context-content')).toBeInTheDocument()
    expect(screen.getByText('Saga history')).toBeInTheDocument()
    expect(screen.getByText('Secret Wars Path')).toBeInTheDocument()
    expect(screen.getByText('StoryArc 1')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-content')).not.toBeInTheDocument()
  })

  it('Show boundaries requests only boundaries and reveals edge content', async () => {
    const user = userEvent.setup()
    const onShowContext = vi.fn()
    const onShowBoundaries = vi.fn()
    const { rerender } = render(
      ratingView({ onShowContext, onShowBoundaries }),
    )

    await user.click(screen.getByRole('button', { name: /show boundaries/i }))
    expect(onShowBoundaries).toHaveBeenCalledTimes(1)
    expect(onShowContext).not.toHaveBeenCalled()

    rerender(
      ratingView({
        onShowContext,
        onShowBoundaries,
        readingBoundariesRequested: true,
        readerContext: populatedContext(),
      }),
    )
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
    expect(screen.getByText('Before this issue')).toBeInTheDocument()
    expect(screen.getByText('After this issue')).toBeInTheDocument()
    expect(screen.getByText('Finish the previous issue first.')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
  })

  it('supports both cards open at once with independent hide controls', async () => {
    const user = userEvent.setup()
    render(
      ratingView({
        readingContextRequested: true,
        readingBoundariesRequested: true,
        readerContext: populatedContext(),
        readingOrders: readingOrdersFixture(),
      }),
    )
    expect(screen.getByTestId('reading-context-content')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide context/i }))
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-content')).toBeInTheDocument()
  })

  it('renders local loading state inside the opened card without touching the rating workflow', () => {
    render(
      ratingView({
        readingContextRequested: true,
        isReaderContextLoading: true,
        readingBoundariesRequested: false,
      }),
    )
    expect(screen.getByTestId('reading-context-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-loading')).not.toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeEnabled()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /snooze/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /cancel roll/i })).toBeEnabled()
  })

  it('renders local error state inside the card while the rating workflow stays usable', () => {
    render(
      ratingView({
        readingBoundariesRequested: true,
        readerContextError: new Error('reader context unavailable'),
      }),
    )
    const error = screen.getByTestId('reading-boundaries-error')
    expect(error).toHaveAttribute('role', 'alert')
    expect(screen.getByText('reader context unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-error')).not.toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeEnabled()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeEnabled()
    expect(screen.queryByText('Your rating')).toBeInTheDocument()
  })

  it('renders truthful empty notes when requested data carries no applicable content', () => {
    render(
      ratingView({
        readingContextRequested: true,
        readingBoundariesRequested: true,
        readerContext: {
          issue_id: 100,
          series: {
            identity_source: 'unavailable',
            canonical_series_id: null,
            series_name: null,
            average_rating: null,
            ratings_count: 0,
            previous_issue: null,
            recent_ratings: [],
            highest_rating: null,
            lowest_rating: null,
          },
          crossovers: [],
          local_chain: {
            issues: [
              { issue_id: 100, issue_number: '3', position: 1, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
            ],
            edges: [],
          },
        },
      }),
    )
    expect(
      screen.getByText('No additional reading context is recorded for this issue.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('No prerequisites or continuity boundaries are recorded for this issue.'),
    ).toBeInTheDocument()
  })

  it('never scrolls the viewport when opening optional content', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    window.HTMLElement.prototype.scrollIntoView = scrollIntoView
    try {
      render(ratingView())
      await user.click(screen.getByRole('button', { name: /show context/i }))
      await user.click(screen.getByRole('button', { name: /show boundaries/i }))
      expect(scrollIntoView).not.toHaveBeenCalled()
    } finally {
      vi.restoreAllMocks()
    }
  })
})

describe('Roll optional reading cards responsive containment (#2764)', () => {
  it('stacks full-width cards that wrap and contain long content without horizontal escape', () => {
    const { container } = render(
      ratingView({
        readingContextRequested: true,
        readingBoundariesRequested: true,
        readerContext: populatedContext(),
        readingOrders: readingOrdersFixture(),
      }),
    )
    const region = container.querySelector('[data-testid="rating-region-reading-optional"]')
    expect(region).not.toBeNull()
    expect(region!.className).toContain('w-full')
    expect(region!.className).toContain('min-w-0')
    expect(region!.className).toContain('space-y-3')

    for (const testId of ['reading-context-card', 'reading-boundaries-card']) {
      const card = container.querySelector(`[data-testid="${testId}"]`)
      expect(card).not.toBeNull()
      expect(card!.className).toContain('w-full')
      expect(card!.className).toContain('min-w-0')
      expect(card!.className).not.toMatch(/grid-cols-\d+/)
      expect(card!.className).not.toMatch(/(md|lg|xl):(col|row)-(start|end|span)/)
    }

    for (const testId of ['reading-context-button', 'reading-boundaries-button']) {
      const button = container.querySelector(`[data-testid="${testId}"]`)
      expect(button).not.toBeNull()
      expect(button!.className).toContain('min-h-9')
      expect(button!.className).toContain('shrink-0')
    }

    for (const testId of ['reading-context-content', 'reading-boundaries-content']) {
      const content = container.querySelector(`[data-testid="${testId}"]`)
      expect(content).not.toBeNull()
      expect(content!.className).toContain('min-w-0')
      expect(content!.className).toContain('max-w-full')
    }
  })
})
