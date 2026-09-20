import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { ReadingContextStatusCard } from '../pages/RollPage/components/ReadingContextStatusCard'
import {
  hasReadingContextContent,
  hasReadingContextInformation,
} from '../pages/RollPage/readingContextContent'
import type { RatingThread } from '../pages/RollPage/types'
import type { ReaderContextResponse } from '../types'

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
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

interface RatingViewOverride {
  activeRatingThread?: Partial<RatingThread> | null
  currentDie?: number
  rolledResult?: number | null
  rating?: number
  predictedDie?: number
  errorMessage?: string
  rateIsPending?: boolean
  snoozeIsPending?: boolean
  dismissIsPending?: boolean
  onUpdateRating?: (value: string) => void
  onSubmitRating?: (finishSession: boolean) => void
  onSnooze?: () => void
  onCancel?: () => void
  onRefreshThread?: () => void
  readerContext?: ReaderContextResponse | null
  isReaderContextLoading?: boolean
  readerContextError?: string | null
}
function renderRatingView(overrides: RatingViewOverride = {}) {
  const defaults = {
    activeRatingThread: {
      id: 1,
      title: 'Ultimate X-Men',
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 12,
      issue_number: '11',
      next_issue_number: '12',
      reading_progress: 'in_progress',
      queue_position: 0,
      issue_id: 100,
      next_issue_id: 101,
    },
    currentDie: 6,
    rolledResult: 5,
    rating: 4,
    predictedDie: 4,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ...callbacks,
    ...overrides,
  }
  return render(<MemoryRouter><RatingView {...defaults} activeRatingThread={defaults.activeRatingThread as RatingThread | null} /></MemoryRouter>)
}

const populatedContext: ReaderContextResponse = {
  issue_id: 100,
  series: {
    identity_source: 'comicvine',
    canonical_series_id: '1-111',
    series_name: 'Ultimate Black Panther',
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
      {
        issue_id: 98,
        issue_number: '3',
        position: 2,
        status: 'read',
        relation: 'previous',
        rating: 3.5,
        crossover_memberships: [],
      },
      {
        issue_id: 100,
        issue_number: '5',
        position: 4,
        status: 'unread',
        relation: 'current',
        rating: null,
        crossover_memberships: [],
      },
    ],
    edges: [
      {
        id: 11,
        kind: 'dependency',
        source_issue_id: 98,
        target_issue_id: 100,
        source_thread_id: 1,
        target_thread_id: 1,
        source_label: 'Ultimate Black Panther #3',
        target_label: 'Ultimate Black Panther #5',
        note: null,
        explanation: 'Blocked by issue #3',
      },
    ],
  },
}

const minimalContext: ReaderContextResponse = {
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
      {
        issue_id: 100,
        issue_number: '5',
        position: 1,
        status: 'unread',
        relation: 'current',
        rating: null,
        crossover_memberships: [],
      },
    ],
    edges: [],
  },
}

describe('RatingView post-#2711: removed Reading Context/Boundaries/WhyThis surfaces', () => {
  it('contains no Why this?, Reading Context or Reading Boundaries affordance and no middle column', () => {
    const { container } = renderRatingView()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-context')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-boundaries')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByText('Your Reading Boundaries')).not.toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('lg:grid-cols-2')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    expect(grid!.contains(screen.getByTestId('rating-region-comic'))).toBe(true)
    expect(grid!.contains(screen.getByTestId('rating-region-decision'))).toBe(true)
  })

  it('still renders rating workflow without removed surfaces even when readerContext is populated', () => {
    renderRatingView({ readerContext: populatedContext })
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-comic')).toBeInTheDocument()
  })

  it('does not render Reading Context pillar content for loaded but empty context', () => {
    renderRatingView({ readerContext: minimalContext })
    expect(screen.queryByText('No reading context available.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
  })
})

describe('Connection history disclosure (#2714)', () => {
  it('renders no narrative heading when only the rating form is meaningful', () => {
    renderRatingView()
    expect(screen.queryByText('Your Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Series history & crossovers')).not.toBeInTheDocument()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
  })

  it('keeps series history hidden behind the disclosure until it is opened', async () => {
    const user = userEvent.setup()
    renderRatingView({ readerContext: populatedContext })
    expect(screen.queryByText('Ultimate Black Panther history')).not.toBeInTheDocument()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.queryByTestId('context-disclosure-content')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /series history & crossovers/i }))
    expect(screen.getByTestId('context-disclosure-content')).toBeVisible()
    expect(screen.getByText('Ultimate Black Panther history')).toBeInTheDocument()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
  })

  it('shows a loading skeleton while reader context loads', () => {
    const { container } = renderRatingView({ isReaderContextLoading: true })
    expect(container.querySelector('.animate-pulse')).not.toBeNull()
    expect(screen.getByRole('slider')).toBeInTheDocument()
  })

  it('reveals crossover analytics inside the disclosure when crossovers exist', async () => {
    const user = userEvent.setup()
    const crossoverContext: ReaderContextResponse = {
      ...populatedContext,
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
      crossovers: [
        {
          id: 500,
          name: 'Secret Wars',
          applies_to_current_issue: true,
          membership_kind: 'issue',
          next_member: null,
          average_rating: 4.0,
          ratings_count: 3,
          read_count: 2,
        },
      ],
    }
    renderRatingView({ readerContext: crossoverContext })
    expect(screen.queryByText('Crossovers')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /series history & crossovers/i }))
    expect(screen.getByText('Crossovers')).toBeInTheDocument()
    expect(screen.getByText('Secret Wars')).toBeInTheDocument()
  })
})

describe('hasReadingContextContent predicate (#1942)', () => {
  it('is false for completely empty state', () => {
    expect(hasReadingContextContent([], [], null)).toBe(false)
  })

  it('is false for a loaded but continuity-free reader context', () => {
    expect(hasReadingContextInformation(minimalContext)).toBe(false)
    expect(hasReadingContextContent([], [], minimalContext)).toBe(false)
  })

  it('is true for reading orders or connected threads alone', () => {
    expect(hasReadingContextContent([{ id: 1, name: 'x', description: null, total_items: 1, completed_items: 1, items: [] }], [], null)).toBe(true)
    expect(hasReadingContextContent([], [{ thread_id: 1, title: 'Other', connection_type: 'blocks', dependency_id: 2 }], null)).toBe(true)
  })

  it('is true for a reader context with edges, a series name, or chain beyond current', () => {
    expect(hasReadingContextInformation(populatedContext)).toBe(true)
    expect(hasReadingContextContent([], [], populatedContext)).toBe(true)
  })
})

describe('ReadingContextStatusCard states (#1942)', () => {
  it('renders the loading copy with a pulse while loading', () => {
    const { container } = render(<ReadingContextStatusCard isLoading error={null} />)
    expect(screen.getByText('Checking reading context…')).toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).not.toBeNull()
  })

  it('renders the error copy with the message when failed', () => {
    render(<ReadingContextStatusCard isLoading={false} error="boom" />)
    expect(screen.getByText('Local reading context unavailable')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('renders nothing when neither loading nor failing', () => {
    const { container } = render(<ReadingContextStatusCard isLoading={false} error={null} />)
    expect(container.textContent).toBe('')
  })
})
