import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
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
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const { comicvineState } = vi.hoisted((): { comicvineState: { metadata: unknown } } => ({
  comicvineState: { metadata: null },
}))
vi.mock('../hooks/useComicVineIssueIntelligence', () => ({
  useComicVineIssueIntelligence: () => ({
    metadata: comicvineState.metadata,
    isLoading: false,
    refetch: vi.fn(),
  }),
}))

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
    ...overrides,
  }
}

function ratingView(overrides: Partial<RatingViewData> = {}) {
  return (
    <MemoryRouter>
      <RatingView data={makeRatingViewData(overrides)} />
    </MemoryRouter>
  )
}

function richReaderContext(): ReaderContextResponse {
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
      ],
    },
  }
}

function gridChildren(container: HTMLElement) {
  const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
  return { grid, cells: Array.from(grid!.querySelectorAll<HTMLElement>(':scope > div')) }
}

describe('RatingView desktop layout respects state instead of reserving fixed coordinates (#2711 revises #1943)', () => {
  it('packs regions without fixed coordinates and reserves no middle column', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    const { grid, cells } = gridChildren(container)
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('grid')
    expect(grid!.className).toContain('items-start')
    expect(grid!.className).toContain('lg:grid-cols-2')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    expect(grid!.className).not.toMatch(/minmax\(0,\d+fr\)/)

    // After #2711, only Comic and Your Context remain (2 cells)
    expect(cells.length).toBe(2)

    expect(cells[0].dataset.testid).toBe('rating-region-comic')
    expect(cells[1].dataset.testid).toBe('rating-region-your-context')
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()

    for (const cell of cells) {
      expect(cell.className).not.toMatch(/\b(?:md:|xl:)?(?:col-start|row-start|col-end|row-end|row-span)-\d+\b/)
      expect(cell.className).not.toMatch(/grid-cols-\d+/)
    }
  })

  it('gives every region a min-w-0 wrapper so content packs without overflow', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    expect(container.querySelector('[data-testid="rating-region-comic"]')!.className).toContain('min-w-0')
    expect(container.querySelector('[data-testid="rating-region-your-context"]')!.className).toContain('min-w-0')
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('stacks the action panel with Your Context instead of below the tallest desktop pillar', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    const yourContext = container.querySelector('[data-testid="rating-region-your-context"]')
    const actions = container.querySelector('[data-testid="rating-actions-grid-cell"]')
    expect(yourContext).not.toBeNull()
    expect(actions).not.toBeNull()
    expect(yourContext!.contains(actions)).toBe(true)
    expect(actions!.className).not.toContain('xl:col-span-full')
    expect(container.querySelector('[data-testid="rating-actions"]')).not.toBeNull()
  })

  it('caps a heavy cover to a viewport-relative budget so actions stay above the fold', () => {
    comicvineState.metadata = {
      comicvine_issue_id: '12345',
      comicvine_url: null,
      series_name: 'Saga',
      series_id: 1,
      issue_number: '3',
      name: 'The Pretending Town',
      description: null,
      image_url: 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=',
      cover_date: '2020-01-01',
      store_date: null,
      creators: [],
      story_arcs: [],
    }
    const { container } = render(ratingView())
    const comicRegion = container.querySelector('[data-testid="rating-region-comic"]')
    const cover = container.querySelector('[data-testid="comic-cover"]')
    const actions = container.querySelector('[data-testid="rating-actions-grid-cell"]')
    const yourContext = container.querySelector('[data-testid="rating-region-your-context"]')
    expect(comicRegion).not.toBeNull()
    expect(cover).not.toBeNull()
    expect(actions).not.toBeNull()
    expect(yourContext).not.toBeNull()
    expect(comicRegion!.contains(cover)).toBe(true)
    expect(yourContext!.contains(actions)).toBe(true)
    const aspectRatioAttr = cover!.getAttribute('data-cover-aspect-ratio')
    const heightCapAttr = cover!.getAttribute('data-cover-height-cap-vh')
    const widthCapAttr = cover!.getAttribute('data-cover-width-cap-vh')
    const aspectRatio = Number(aspectRatioAttr)
    const heightCap = Number(heightCapAttr)
    const widthCap = Number(widthCapAttr)
    expect(Number.isFinite(aspectRatio)).toBe(true)
    expect(aspectRatio).toBeGreaterThan(0)
    expect(heightCap).toBe(45)
    expect(Number.isFinite(widthCap)).toBe(true)
    expect(widthCap).toBeGreaterThan(0)
    expect(widthCap).toBeCloseTo(heightCap * aspectRatio)
    expect(cover!.className).not.toContain('max-h-')
  })
})

describe('RatingView reading-context affordances retired (#2711)', () => {
  it('contains no Why this?, Reading Context or Reading Boundaries affordance', () => {
    render(ratingView())
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })
})

afterEach(() => {
  comicvineState.metadata = null
})
