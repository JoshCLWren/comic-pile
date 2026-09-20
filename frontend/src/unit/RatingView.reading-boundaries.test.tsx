import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { ReaderContextResponse } from '../types'
import type { RatingThread } from '../pages/RollPage/types'

vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))
vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

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

interface RatingViewOverride {
  activeRatingThread?: Partial<RatingThread> | null
  rolledResult?: number | null
  errorMessage?: string
  readerContext?: ReaderContextResponse | null
  isReaderContextLoading?: boolean
  readerContextError?: string | null
}
function ratingView(overrides: RatingViewOverride = {}) {
  const defaults = {
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
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onCancel: vi.fn(),
    onRefreshThread: vi.fn(),
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ...overrides,
  }
  return <MemoryRouter><RatingView {...defaults} activeRatingThread={defaults.activeRatingThread as RatingThread | null} /></MemoryRouter>
}

describe('RatingView Reading Boundaries retired control (#2711 supersedes #2519)', () => {
  it('renders no Reading Context or Reading Boundaries lazy controls without an active rating thread', () => {
    render(ratingView({ activeRatingThread: null }))
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('renders no lazy controls even with populated reader context', () => {
    render(ratingView({
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
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByText('Your Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
  })

  it('reserves no middle-column region after removal', () => {
    const { container } = render(ratingView({
      readerContext: makeContext([], 'Saga'),
    }))
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('lg:grid-cols-2')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
  })

  it('does not render boundaries section even when edges exist', () => {
    render(ratingView({
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
    expect(screen.queryByText('Your Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByText('Continuity:')).not.toBeInTheDocument()
  })

  it('still renders comic and your-context regions and rating actions', () => {
    render(ratingView({ readerContext: makeContext([], 'Saga') }))
    expect(screen.getByTestId('rating-region-comic')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-your-context')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })
})
