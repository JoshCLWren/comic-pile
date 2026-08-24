import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RatingThread } from '../pages/RollPage/types'
import { RatingView } from '../pages/RollPage/components/RatingView'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => <div data-testid="readiness-summary">Ready to read</div>,
}))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))
vi.mock('../pages/RollPage/components/SeriesPanel', () => ({
  SeriesPanel: () => <div data-testid="series-panel">Series history</div>,
}))
vi.mock('../pages/RollPage/components/CrossoverAnalytics', () => ({
  CrossoverAnalytics: () => <div data-testid="crossover-analytics">Crossovers analytics</div>,
}))
vi.mock('../pages/RollPage/components/ComicPillar', () => ({
  ComicPillar: () => <div data-testid="comic-pillar">Comic pillar</div>,
}))

const mockUseReaderContext = vi.fn()
vi.mock('../hooks/useReaderContext', () => ({
  useReaderContext: (...args: unknown[]) => mockUseReaderContext(...args),
}))

const baseThread: RatingThread = {
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
  last_rolled_result: 3,
}

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderView(overrides: Partial<React.ComponentProps<typeof RatingView>> = {}) {
  return render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={baseThread}
        currentDie={6}
        rolledResult={3}
        rating={4.0}
        predictedDie={4}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        {...callbacks}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockUseReaderContext.mockReturnValue({
    context: {
      issue_id: 100,
      series: {
        identity_source: 'comicvine',
        canonical_series_id: '1',
        series_name: 'Saga',
        average_rating: 4.2,
        ratings_count: 7,
        previous_issue: null,
        recent_ratings: [],
        highest_rating: null,
        lowest_rating: null,
      },
      crossovers: [
        {
          id: 7,
          name: 'Test Crossover',
          applies_to_current_issue: false,
          next_member: null,
          average_rating: null,
          ratings_count: 0,
          read_count: 0,
        },
      ],
      local_chain: {
        issues: [
          { issue_id: 100, issue_number: '4', position: 4, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] },
        ],
        edges: [
          {
            id: 1,
            kind: 'dependency',
            source_issue_id: 99,
            target_issue_id: 100,
            source_thread_id: 1,
            target_thread_id: 1,
            source_label: 'Saga #3',
            target_label: 'Saga #4',
            note: null,
            explanation: 'Requires Saga #3',
          },
        ],
      },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })
})

describe('RatingView reader-first hierarchy #1875', () => {
  it('renders the four reader questions in order, not backend names', () => {
    renderView()

    const hierarchy = screen.getByTestId('roll-result-hierarchy')
    const headings = within(hierarchy).getAllByRole('heading', { level: 2 })
    const texts = headings.map((h) => h.textContent)

    expect(texts).toEqual([
      'What am I reading?',
      'Why this one / can I read it?',
      "What's connected?",
      'Engine details',
    ])

    // Verify order via DOM position: What am I reading appears before Why this one etc.
    const what = screen.getByTestId('tier-what-am-i-reading')
    const why = screen.getByTestId('tier-why-this-one')
    const connected = screen.getByTestId('tier-whats-connected')
    const engine = screen.getByTestId('tier-engine-details')

    const allTiers = [what, why, connected, engine]
    for (let i = 0; i < allTiers.length - 1; i++) {
      expect(allTiers[i].compareDocumentPosition(allTiers[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }

    // Ensure implementation vocabulary is not used as top-level headings in primary workflow
    expect(screen.queryByText('EXACT CROSSOVER CONTEXT')).not.toBeInTheDocument()
    expect(screen.queryByText('DEPENDENCY & CONTINUITY EDGES')).not.toBeInTheDocument()
    expect(screen.queryByText('LOCAL SERIES CHAIN')).not.toBeInTheDocument()
  })

  it('shows readability context before graph internals', () => {
    renderView()
    const why = screen.getByTestId('tier-why-this-one')
    const connected = screen.getByTestId('tier-whats-connected')
    expect(why.compareDocumentPosition(connected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(why).getByTestId('readiness-summary')).toBeInTheDocument()
    // Story connections should be inside What's connected, not in Why tier
    expect(within(connected).getByText('Story connections')).toBeInTheDocument()
  })

  it('groups crossover/dependency under Whats connected tier', () => {
    renderView()
    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('Crossovers for this issue')).toBeInTheDocument()
    expect(within(connected).getByText('Story connections')).toBeInTheDocument()
    // Crossovers heading should not be a top-level engine heading
    expect(screen.queryByText('READING ROUTES')).not.toBeInTheDocument()
  })

  it('keeps engine details collapsed by default and reachable on demand', async () => {
    const user = userEvent.setup()
    renderView()
    const details = screen.getByTestId('tier-engine-details') as HTMLDetailsElement
    expect(details.open).toBe(false)

    // Ladder state should be inside engine details, not visible in primary tiers
    expect(within(details).getByText(/Rolled 3 on d6/)).toBeInTheDocument()
    expect(within(details).getByTestId('engine-diagnostics')).toBeInTheDocument()

    // Rating workflow should not require opening engine details
    expect(screen.getByRole('slider')).toBeInTheDocument()
    expect(screen.getByTestId('save-and-continue')).toBeInTheDocument()

    // Click summary to open
    const summary = within(details).getByText('Engine details')
    await user.click(summary)
    expect(details.open).toBe(true)
    // Still contains diagnostics after open
    expect(within(details).getByTestId('engine-diagnostics')).toBeInTheDocument()
  })

  it('does not require edge/route vocabulary to submit rating', () => {
    renderView()
    const slider = screen.getByRole('slider', { name: /Rating from/ })
    expect(slider).toBeInTheDocument()
    // Ensure slider is outside engine details
    const details = screen.getByTestId('tier-engine-details')
    expect(details.contains(slider)).toBe(false)
  })

  it('preserves existing functionality (snooze, cancel, save) after hierarchy change', async () => {
    const user = userEvent.setup()
    renderView()
    await user.click(screen.getByRole('button', { name: /Snooze/ }))
    expect(callbacks.onSnooze).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /Cancel roll/ }))
    expect(callbacks.onCancel).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /Mark read & save/ }))
    expect(callbacks.onSubmitRating).toHaveBeenCalled()
  })

  it('keeps correction tooling inside engine details', () => {
    renderView({
      connectedThreads: [{ thread_id: 2, title: 'Other', connection_type: 'blocks', dependency_id: 1 }],
    })
    const details = screen.getByTestId('tier-engine-details')
    expect(within(details).getByText('Correct continuity')).toBeInTheDocument()
  })
})

type LocalIssueLike = {
  issue_id: number
  issue_number: string
  position: number
  status: string
  relation: 'previous' | 'current' | 'next' | 'future'
  rating: number | null
  crossover_memberships: { id: number; name: string }[]
}

type EdgeLike = {
  id: number
  kind: 'dependency' | 'continuity'
  source_issue_id: number
  target_issue_id: number
  source_thread_id: number | null
  target_thread_id: number | null
  source_label: string | null
  target_label: string | null
  note: string | null
  explanation: string | null
}

function makeIssue(overrides: Partial<LocalIssueLike> = {}): LocalIssueLike {
  return {
    issue_id: 100,
    issue_number: '4',
    position: 4,
    status: 'unread',
    relation: 'current',
    rating: null,
    crossover_memberships: [],
    ...overrides,
  }
}

function makeEdge(overrides: Partial<EdgeLike>): EdgeLike {
  return {
    id: 1,
    kind: 'dependency',
    source_issue_id: 99,
    target_issue_id: 100,
    source_thread_id: null,
    target_thread_id: null,
    source_label: null,
    target_label: null,
    note: null,
    explanation: null,
    ...overrides,
  }
}

function makeCrossover(overrides: Partial<{ id: number; name: string; applies_to_current_issue: boolean; next_member: { issue_id: number; issue_number: string } | null }>) {
  return {
    id: 7,
    name: 'Test Crossover',
    applies_to_current_issue: false,
    next_member: null,
    average_rating: null,
    ratings_count: 0,
    read_count: 0,
    ...overrides,
  }
}

const baseSeries = {
  identity_source: 'comicvine',
  canonical_series_id: '1',
  series_name: 'Saga',
  average_rating: 4.2,
  ratings_count: 7,
  previous_issue: null,
  recent_ratings: [],
  highest_rating: null,
  lowest_rating: null,
}

function setContext(issues: LocalIssueLike[], edges: EdgeLike[] = [], crossovers: ReturnType<typeof makeCrossover>[] = []) {
  mockUseReaderContext.mockReturnValue({
    context: { issue_id: 100, series: baseSeries, crossovers, local_chain: { issues, edges } },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })
}

describe('RatingView reader-first chain and connection rendering #1875', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders previous ratings as stars, marks the current issue, and keeps chain order', () => {
    setContext([
      makeIssue({ issue_id: 98, issue_number: '2', position: 2, relation: 'previous', rating: 3 }),
      makeIssue({ issue_id: 99, issue_number: '3', position: 3, relation: 'previous', rating: 4.5 }),
      makeIssue({ issue_id: 100, issue_number: '4', position: 4, relation: 'current' }),
      makeIssue({ issue_id: 101, issue_number: '5', position: 5, relation: 'next' }),
    ])
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('★★★★½')).toBeInTheDocument()
    expect(within(connected).getByText('★★★')).toBeInTheDocument()
    expect(within(connected).getAllByLabelText(/Your rating: /)).toHaveLength(2)
    expect(within(connected).getByText('You are here')).toBeInTheDocument()

    const rowLabels = within(connected)
      .getAllByLabelText(/Open Saga issue /)
      .map((row) => row.getAttribute('aria-label'))
    expect(rowLabels).toEqual(['Open Saga issue 2', 'Open Saga issue 3', 'Open Saga issue 4', 'Open Saga issue 5'])
  })

  it('renders the local chain without a current issue', () => {
    setContext([
      makeIssue({ issue_id: 99, issue_number: '3', position: 3, relation: 'previous' }),
      makeIssue({ issue_id: 101, issue_number: '5', position: 5, relation: 'next' }),
    ])
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).queryByText('You are here')).not.toBeInTheDocument()
    expect(within(connected).getByLabelText('Open Saga issue 3')).toBeInTheDocument()
    expect(within(connected).getByLabelText('Open Saga issue 5')).toBeInTheDocument()
  })

  it('opens the thread from a series row via click and keyboard activation', async () => {
    const user = userEvent.setup()
    setContext([makeIssue()])
    renderView()

    const row = screen.getByLabelText('Open Saga issue 4')
    await user.click(row)
    expect(mockNavigate).toHaveBeenCalledWith('/thread/1')

    mockNavigate.mockClear()
    fireEvent.keyDown(row, { key: 'Enter' })
    fireEvent.keyDown(row, { key: ' ' })
    expect(mockNavigate).toHaveBeenCalledTimes(2)
  })

  it('does not navigate from a series row when no thread is active', () => {
    setContext([makeIssue()])
    renderView({ activeRatingThread: null })

    fireEvent.click(screen.getByLabelText('Open Loading… issue 4'))
    expect(mockNavigate).not.toHaveBeenCalledWith(expect.stringMatching(/^\/thread\//))
  })

  it('dedupes crossover memberships across the local chain and lists them in diagnostics', () => {
    setContext([
      makeIssue({
        issue_id: 99,
        issue_number: '3',
        position: 3,
        relation: 'previous',
        crossover_memberships: [
          { id: 7, name: 'Alpha Cross' },
          { id: 8, name: 'Beta Cross' },
        ],
      }),
      makeIssue({
        crossover_memberships: [
          { id: 7, name: 'Alpha Cross' },
          { id: 9, name: 'Gamma Cross' },
        ],
      }),
    ])
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getAllByRole('button', { name: 'Open Alpha Cross crossover' })).toHaveLength(1)
    expect(within(connected).getByRole('button', { name: 'Open Beta Cross crossover' })).toBeInTheDocument()
    expect(within(connected).getByRole('button', { name: 'Open Gamma Cross crossover' })).toBeInTheDocument()

    const details = screen.getByTestId('tier-engine-details')
    expect(within(details).getByText('Memberships: Alpha Cross, Beta Cross, Gamma Cross')).toBeInTheDocument()
  })

  it('shows current-issue and upcoming crossovers with next member info', async () => {
    const user = userEvent.setup()
    setContext(
      [makeIssue({ crossover_memberships: [{ id: 9, name: 'Current Cross' }] })],
      [],
      [
        makeCrossover({ id: 9, name: 'Current Cross', applies_to_current_issue: true }),
        makeCrossover({
          id: 10,
          name: 'Upcoming Cross',
          applies_to_current_issue: false,
          next_member: { issue_id: 200, issue_number: '7' },
        }),
      ],
    )
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('Crossovers for this issue')).toBeInTheDocument()
    expect(within(connected).getByText('Current issue crossovers')).toBeInTheDocument()
    expect(within(connected).getByText('Upcoming crossovers')).toBeInTheDocument()
    expect(within(connected).getByText('— starts at #7')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Open crossover Upcoming Cross' }))
    expect(mockNavigate).toHaveBeenCalledWith('/crossovers')
  })

  it('labels blocked-by dependencies in reader language with fallback labels and notes', () => {
    setContext(
      [makeIssue()],
      [
        makeEdge({
          id: 11,
          kind: 'dependency',
          source_issue_id: 98,
          target_issue_id: 100,
          source_label: null,
          target_label: null,
          note: 'Needs the earlier arc first',
          explanation: null,
        }),
      ],
    )
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('Blocked by:')).toBeInTheDocument()
    expect(within(connected).getByText('#98')).toBeInTheDocument()
    expect(within(connected).getByText('#100')).toBeInTheDocument()
    expect(within(connected).getByText('Needs the earlier arc first')).toBeInTheDocument()
  })

  it('labels blocking dependencies when this issue unblocks later issues', () => {
    setContext(
      [makeIssue()],
      [
        makeEdge({
          id: 12,
          kind: 'dependency',
          source_issue_id: 100,
          target_issue_id: 102,
          source_thread_id: 5,
          source_label: 'Saga #4',
          target_thread_id: null,
          target_label: 'Tie-in #1',
          explanation: 'Read this before the tie-in',
        }),
      ],
    )
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('Blocks:')).toBeInTheDocument()
    expect(within(connected).getByRole('button', { name: 'Open thread for Saga #4' })).toBeInTheDocument()
    expect(within(connected).getByText('Tie-in #1')).toBeInTheDocument()
    expect(within(connected).getByText('Read this before the tie-in')).toBeInTheDocument()
  })

  it('labels mixed connections and renders continuity links with diagnostics', () => {
    setContext(
      [makeIssue()],
      [
        makeEdge({ id: 13, kind: 'dependency', source_issue_id: 98, target_issue_id: 102 }),
        makeEdge({
          id: 14,
          kind: 'continuity',
          source_issue_id: 100,
          target_issue_id: 103,
          source_thread_id: 1,
          target_thread_id: null,
          source_label: 'Saga #4',
          target_label: 'Tie-in #2',
          note: 'Same event, later scene',
          explanation: null,
        }),
        makeEdge({
          id: 15,
          kind: 'continuity',
          source_issue_id: 104,
          target_issue_id: 105,
          source_thread_id: null,
          target_thread_id: 2,
          explanation: 'Continues directly',
        }),
      ],
    )
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('Connections:')).toBeInTheDocument()
    expect(within(connected).getByText('Continuity:')).toBeInTheDocument()
    expect(within(connected).getByText('Same event, later scene')).toBeInTheDocument()
    expect(within(connected).getByText('#104')).toBeInTheDocument()
    expect(within(connected).getByRole('button', { name: 'Open thread for #105' })).toBeInTheDocument()
    expect(within(connected).getByText('Continues directly')).toBeInTheDocument()

    const details = screen.getByTestId('tier-engine-details')
    expect(within(details).getByText('Dependency edges: 13')).toBeInTheDocument()
    expect(within(details).getByText('Continuity edges: 14, 15')).toBeInTheDocument()
  })

  it('shows empty-state copy when reader context is missing', () => {
    mockUseReaderContext.mockReturnValue({ context: undefined, isLoading: false, error: null, refetch: vi.fn() })
    renderView()

    const connected = screen.getByTestId('tier-whats-connected')
    expect(within(connected).getByText('No crossover or connection data for this issue yet.')).toBeInTheDocument()
    // Without reader context the view must not claim readiness.
    expect(within(screen.getByTestId('tier-why-this-one')).queryByText('No blockers reported for this issue. Ready to read.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('series-panel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('crossover-analytics')).not.toBeInTheDocument()
  })

  it('shows a placeholder roll result inside engine details when nothing was rolled', () => {
    setContext([makeIssue()])
    renderView({ rolledResult: null })

    const details = screen.getByTestId('tier-engine-details')
    expect(within(details).getAllByText('Roll Result').length).toBeGreaterThan(0)
    expect(within(details).getByText('—')).toBeInTheDocument()
  })

  it('marks the last issue of a thread in the save action', () => {
    setContext([makeIssue()])
    renderView({ activeRatingThread: { ...baseThread, issues_remaining: 1 } })

    expect(screen.getByText('This is the last issue in the thread')).toBeInTheDocument()
    expect(screen.getByTestId('save-and-continue')).toHaveTextContent('Mark read & complete')
  })
})
