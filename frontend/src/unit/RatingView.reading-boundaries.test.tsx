import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { ReaderContextResponse } from '../types'
import type { RatingThread } from '../pages/RollPage/types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

beforeEach(() => {
  navigateSpy.mockClear()
})

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

interface HoistedComicVineModule {
  comicvineState: {
    metadata: unknown
  }
}

const { comicvineState } = vi.hoisted((): HoistedComicVineModule => ({
  comicvineState: { metadata: null },
}))
vi.mock('../hooks/useComicVineIssueIntelligence', () => ({
  useComicVineIssueIntelligence: () => ({
    metadata: comicvineState.metadata,
    isLoading: false,
    refetch: vi.fn(),
  }),
}))

interface TestEdge {
  id: number
  kind: 'dependency' | 'continuity'
  source_issue_id: number
  target_issue_id: number
  source_thread_id: number | null
  target_thread_id: number | null
  source_label: string | null
  target_label: string | null
  source_status: 'read' | 'unread'
  target_status: 'read' | 'unread'
  note: string | null
  explanation: string | null
}

function edge(overrides: Partial<TestEdge> = {}): TestEdge {
  return {
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
    explanation: null,
    ...overrides,
  }
}

function makeContext(edges: TestEdge[], seriesName: string | null = null): ReaderContextResponse {
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
  onFetchReadingDetails?: (threadId: number | null) => void
  onFetchReadingContext?: (threadId: number | null) => void
  onFetchReadingBoundaries?: (threadId: number | null) => void
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
  return <MemoryRouter><RatingView {...defaults} activeRatingThread={defaults.activeRatingThread as RatingThread | null} /></MemoryRouter>
}

describe('RatingView Reading Boundaries lazy control (issue #2519)', () => {
  it('renders no lazy controls without an active rating thread', () => {
    render(ratingView({ activeRatingThread: null }))
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
  })

  it('shows dependency edges with a Blocked by heading and its explanation after expansion', async () => {
    render(ratingView({
      readerContext: makeContext([edge({ explanation: 'Finish the previous issue first.' })]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('Blocked by:')).toBeInTheDocument()
    expect(within(section).getByText('#2')).toBeInTheDocument()
    expect(within(section).getByText('#3')).toBeInTheDocument()
    expect(within(section).getByText('Finish the previous issue first.')).toBeInTheDocument()
  })

  it('uses a Blocks heading when every dependency edge leaves the current issue', async () => {
    render(ratingView({
      readerContext: makeContext([edge({ source_issue_id: 100, source_label: '#3', target_issue_id: 101, target_label: '#4' })]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('Blocks:')).toBeInTheDocument()
  })

  it('falls back to the generic heading for a mixed set of dependency edges', async () => {
    render(ratingView({
      readerContext: makeContext([
        edge({ id: 1, source_issue_id: 98, target_issue_id: 100 }),
        edge({ id: 2, source_issue_id: 100, source_label: '#3', target_issue_id: 101, target_label: '#4' }),
      ]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('Dependency edges:')).toBeInTheDocument()
  })

  it('renders a single continuity edge with issue-id fallback labels and its note', async () => {
    render(ratingView({
      readerContext: makeContext([
        edge({
          kind: 'continuity',
          source_issue_id: 99,
          source_label: null,
          target_issue_id: 100,
          target_label: null,
          note: 'Crossover order',
        }),
      ]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('Continuity:')).toBeInTheDocument()
    expect(within(section).getByText('#99')).toBeInTheDocument()
    expect(within(section).getByText('#100')).toBeInTheDocument()
    expect(within(section).getByText('Crossover order')).toBeInTheDocument()
  })

  it('uses the plural heading for multiple continuity edges', async () => {
    render(ratingView({
      readerContext: makeContext([
        edge({ id: 1, kind: 'continuity', source_issue_id: 98, target_issue_id: 100 }),
        edge({ id: 2, kind: 'continuity', source_issue_id: 99, source_label: '#1', target_issue_id: 100, target_label: '#3' }),
      ]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('Continuity edges:')).toBeInTheDocument()
  })

  it('omits the italic explanation when an edge has neither a note nor an explanation', async () => {
    render(ratingView({
      readerContext: makeContext([edge()]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(within(section).getByText('#2')).toBeInTheDocument()
    expect(section.querySelector('.italic')).toBeNull()
  })

  it('shows the loading card while a boundaries request is pending', async () => {
    render(ratingView({
      readerContext: null,
      isReaderContextLoading: true,
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Checking reading context…')).toBeInTheDocument()
  })

  it('shows the failure card when the boundaries request fails', async () => {
    render(ratingView({
      readerContext: null,
      readerContextError: 'Reader context failed',
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Local reading context unavailable')).toBeInTheDocument()
    expect(screen.getByText('Reader context failed')).toBeInTheDocument()
  })

  it('shows an empty message when no edges exist', async () => {
    render(ratingView({
      readerContext: makeContext([]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('No reading boundaries available.')).toBeInTheDocument()
  })

  it('treats an edges-only context as an empty Reading Context but a populated Reading Boundaries region', async () => {
    render(ratingView({
      readerContext: makeContext([edge({ explanation: 'Finish the previous issue first.' })]),
    }))
    const user = userEvent.setup()
    await user.click(screen.getByTestId('reading-context-button'))
    expect(screen.getByText('No reading context available.')).toBeInTheDocument()
    expect(screen.queryByText('Your Reading Boundaries')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Your Reading Boundaries')).toBeInTheDocument()
    expect(screen.getByText('No reading context available.')).toBeInTheDocument()
  })

  it('lets Reading Context and Reading Boundaries expand and coexist independently', async () => {
    render(ratingView({
      readerContext: makeContext([edge()], 'Saga'),
    }))
    const user = userEvent.setup()
    await user.click(screen.getByTestId('reading-context-button'))
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByText('Your Reading Boundaries')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('reading-boundaries-button'))
    expect(screen.getByText('Your Reading Boundaries')).toBeInTheDocument()
    expect(screen.getByText('Saga')).toBeInTheDocument()
  })

  it('dispatches to the dedicated Reading Context callback when provided', async () => {
    const onFetchReadingContext = vi.fn()
    const onFetchReadingDetails = vi.fn()
    render(ratingView({ onFetchReadingContext, onFetchReadingDetails }))
    await userEvent.setup().click(screen.getByTestId('reading-context-button'))
    expect(onFetchReadingContext).toHaveBeenCalledWith(1)
    expect(onFetchReadingDetails).not.toHaveBeenCalled()
  })

  it('falls back to the shared Reading Context fetch when the dedicated callback is absent', async () => {
    const onFetchReadingDetails = vi.fn()
    render(ratingView({ onFetchReadingDetails }))
    await userEvent.setup().click(screen.getByTestId('reading-context-button'))
    expect(onFetchReadingDetails).toHaveBeenCalledWith(1)
  })

  it('dispatches to the dedicated Reading Boundaries callback when provided', async () => {
    const onFetchReadingBoundaries = vi.fn()
    const onFetchReadingDetails = vi.fn()
    render(ratingView({ onFetchReadingBoundaries, onFetchReadingDetails }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    expect(onFetchReadingBoundaries).toHaveBeenCalledWith(1)
    expect(onFetchReadingDetails).not.toHaveBeenCalled()
  })

  it('falls back to the shared Reading Boundaries fetch when the dedicated callback is absent', async () => {
    const onFetchReadingDetails = vi.fn()
    render(ratingView({ onFetchReadingDetails }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    expect(onFetchReadingDetails).toHaveBeenCalledWith(1)
  })

  it('shows a bounded status strip below both controls while loading before any expansion', () => {
    render(ratingView({
      readerContext: null,
      isReaderContextLoading: true,
    }))
    expect(screen.getByText('Checking reading context…')).toBeInTheDocument()
  })

  it('shows a bounded failure strip below both controls before any expansion', () => {
    render(ratingView({
      readerContext: null,
      readerContextError: 'Reader context failed',
    }))
    expect(screen.getByText('Local reading context unavailable')).toBeInTheDocument()
  })

  it('navigates to dependency endpoint threads when source and target have thread ids', async () => {
    render(ratingView({
      readerContext: makeContext([edge({ source_thread_id: 42, target_thread_id: 43 })]),
    }))
    const user = userEvent.setup()
    await user.click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    await user.click(within(section).getByRole('button', { name: 'Open series for #2' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/42')
    await user.click(within(section).getByRole('button', { name: 'Open series for #3' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/43')
  })

  it('navigates to continuity endpoint threads when source and target have thread ids', async () => {
    render(ratingView({
      readerContext: makeContext([
        edge({
          kind: 'continuity',
          source_issue_id: 99,
          source_label: null,
          target_issue_id: 100,
          target_label: null,
          source_thread_id: 52,
          target_thread_id: 53,
          note: 'Crossover order',
        }),
      ]),
    }))
    const user = userEvent.setup()
    await user.click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    await user.click(within(section).getByRole('button', { name: 'Open series for #99' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/52')
    await user.click(within(section).getByRole('button', { name: 'Open series for #100' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/53')
  })

  it('leaves boundary endpoints without a thread id as inert text instead of navigation buttons', async () => {
    render(ratingView({
      readerContext: makeContext([edge()]),
    }))
    await userEvent.setup().click(screen.getByTestId('reading-boundaries-button'))
    const section = screen.getByText('Your Reading Boundaries').closest('section')!
    expect(section.querySelector('button[aria-label^="Open series for"]')).toBeNull()
    expect(within(section).getByText('#2')).toBeInTheDocument()
    expect(within(section).getByText('#3')).toBeInTheDocument()
  })
})

afterEach(() => {
  comicvineState.metadata = null
})