import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

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

const baseThread = {
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
} as never

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
