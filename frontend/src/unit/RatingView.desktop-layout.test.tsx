import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
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
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const { comicvineState } = vi.hoisted(() => ({
  comicvineState: { metadata: null as unknown },
}))
vi.mock('../hooks/useComicVineIssueIntelligence', () => ({
  useComicVineIssueIntelligence: () => ({
    metadata: comicvineState.metadata,
    isLoading: false,
    refetch: vi.fn(),
  }),
}))

function readingOrders(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    id: 10 + index,
    name: `Reading order ${index + 1}`,
    description: null,
    total_items: 8,
    completed_items: 3,
    items: [],
  }))
}

function connectedThreads(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    thread_id: 200 + index,
    title: `Connected thread ${index + 1}`,
    connection_type: 'blocked_by' as const,
    dependency_id: 1 + index,
  }))
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

function sparseReaderContext(): ReaderContextResponse {
  return {
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
  }
}

function ratingView(overrides: Record<string, unknown> = {}) {
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
    readingOrders: [],
    connectedThreads: [],
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
  return <MemoryRouter><RatingView {...defaults} /></MemoryRouter>
}

function gridChildren(container: HTMLElement) {
  const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
  return { grid, cells: Array.from(grid!.querySelectorAll(':scope > div')) }
}

interface LayoutStateCase {
  name: string
  readingOrders: number
  connectedThreads: number
  readerContext: ReaderContextResponse | null
  expectReadingContextRegion: boolean
}

const layoutCases: LayoutStateCase[] = [
  { name: 'rich continuity state', readingOrders: 2, connectedThreads: 2, readerContext: richReaderContext(), expectReadingContextRegion: true },
  { name: 'sparse continuity state', readingOrders: 1, connectedThreads: 1, readerContext: sparseReaderContext(), expectReadingContextRegion: true },
  { name: 'no meaningful reading context state', readingOrders: 0, connectedThreads: 0, readerContext: null, expectReadingContextRegion: false },
  { name: 'cover-heavy state', readingOrders: 0, connectedThreads: 0, readerContext: null, expectReadingContextRegion: false },
]

describe('RatingView desktop layout respects state instead of reserving fixed coordinates (issue #1943)', () => {
  it.each(layoutCases)('packs regions without fixed coordinates in $name', (state) => {
    const { container } = render(
      ratingView({
        readingOrders: readingOrders(state.readingOrders),
        connectedThreads: connectedThreads(state.connectedThreads),
        readerContext: state.readerContext,
      }),
    )
    const { grid, cells } = gridChildren(container)
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('grid')
    expect(grid!.className).toContain('items-start')
    expect(grid!.className).toContain('xl:grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))]')
    expect(grid!.className).not.toMatch(/minmax\(0,\d+fr\)/)

    const expectedRegionCount = state.expectReadingContextRegion ? 3 : 2
    expect(cells.length).toBe(expectedRegionCount + 1)

    expect(cells[0].dataset.testid).toBe('rating-region-comic')
    if (state.expectReadingContextRegion) {
      expect(cells[1].dataset.testid).toBe('rating-region-reading-context')
      expect(cells[2].dataset.testid).toBe('rating-region-your-context')
    } else {
      expect(cells[1].dataset.testid).toBe('rating-region-your-context')
    }
    expect(cells[cells.length - 1].dataset.testid).toBe('rating-actions-grid-cell')

    for (const cell of cells) {
      expect(cell.className).not.toMatch(/\b(?:md:|xl:)?(?:col-start|row-start|col-end|row-end|row-span)-\d+\b/)
      expect(cell.className).not.toMatch(/grid-cols-\d+/)
    }
  })

  it.each(layoutCases)('gives every region a min-w-0 wrapper so content packs without overflow in $name', (state) => {
    const { container } = render(
      ratingView({
        readingOrders: readingOrders(state.readingOrders),
        connectedThreads: connectedThreads(state.connectedThreads),
        readerContext: state.readerContext,
      }),
    )
    for (const region of ['rating-region-comic', 'rating-region-your-context', ...(state.expectReadingContextRegion ? ['rating-region-reading-context'] : [])]) {
      const wrapper = container.querySelector(`[data-testid="${region}"]`)
      expect(wrapper).not.toBeNull()
      expect(wrapper!.className).toContain('min-w-0')
    }
  })

  it('places the action panel on its own full-width desktop row below every region', () => {
    const { container } = render(
      ratingView({
        readingOrders: readingOrders(2),
        connectedThreads: connectedThreads(2),
        readerContext: richReaderContext(),
      }),
    )
    const { cells } = gridChildren(container)
    const actions = cells[cells.length - 1]
    expect(actions.dataset.testid).toBe('rating-actions-grid-cell')
    expect(actions.className).toContain('xl:col-span-full')
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
    expect(comicRegion).not.toBeNull()
    expect(cover).not.toBeNull()
    expect(comicRegion!.contains(cover)).toBe(true)
    expect(cover!.className).toContain('max-h-[min(70vh,45vh)]')
    expect(cover!.className).not.toContain('max-h-[70vh]')
  })
})

describe('RatingView reading-context presence contract (issue #1943 prerequisite)', () => {
  it('omits the Reading Context region entirely when there is no meaningful continuity content', () => {
    render(ratingView())
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
  })

  it('renders the Reading Context region when reading orders exist', () => {
    render(ratingView({ readingOrders: readingOrders(1) }))
    expect(screen.getByText('Reading Context')).toBeInTheDocument()
  })

  it('renders the Reading Context region when connected threads exist even with no reading orders', () => {
    render(ratingView({ connectedThreads: connectedThreads(1) }))
    expect(screen.getByText('Reading Context')).toBeInTheDocument()
  })
})

afterEach(() => {
  comicvineState.metadata = null
})