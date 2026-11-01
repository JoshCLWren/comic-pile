import { render, screen, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread } from '../types/rollBootstrap'

type ThreadPoolProps = Parameters<typeof ThreadPool>[0]

const mockPool: RollBootstrapThread[] = [
  {
    id: 1,
    title: 'The Amazing Spider-Man',
    format: 'Mainline',
    issue_number: '1',
    route_labels: ['Main Story'],
  },
  {
    id: 2,
    title: 'Batman',
    format: 'DC',
    issue_number: '1',
    route_labels: ['Main Story'],
  },
]

const baseProps: ThreadPoolProps = {
  pool: mockPool,
  dieSize: 20,
  isRatingView: false,
  selectedThreadId: null,
  snoozedThreads: [],
  snoozedExpanded: false,
  skippedThreads: [],
  skippedExpanded: false,
  onThreadClick: () => {},
  onUnsnooze: () => {},
  onUnskip: () => {},
  onToggleSnoozed: () => {},
  onToggleSkipped: () => {},
  onShuffle: () => {},
  unsnoozeIsPending: false,
  unskipIsPending: false,
  shuffleIsPending: false,
}

function renderPool(overrides: Partial<ThreadPoolProps> = {}) {
  return render(
    <MemoryRouter>
      <ThreadPool {...baseProps} {...overrides} />
    </MemoryRouter>,
  )
}

describe('ThreadPool Component', () => {
  it('renders no raw identifiers in die faces', () => {
    renderPool()

    const dieFaces = screen.getAllByRole('button', { name: /die face/i })
    expect(dieFaces.length).toBe(mockPool.length)

    dieFaces.forEach((element) => {
      expect(element).not.toHaveTextContent(/Thread \d+/i)
      expect(element).not.toHaveTextContent(/Issue \d+/i)
      expect(element).not.toHaveTextContent(/ComicVine #\d+/i)
    })
  })

  it('uses one vocabulary term and shows comic titles instead of IDs', () => {
    renderPool()

    const dieFaces = screen.getAllByRole('button', { name: /die face/i })
    dieFaces.forEach((element) => {
      const label = element.getAttribute('aria-label') || ''
      expect(label).toMatch(/connected to/i)
      expect(label).not.toMatch(/\broutes\b/i)
      expect(element.textContent).toMatch(/The Amazing Spider-Man|Batman/)
      expect(element).not.toHaveTextContent(/Issue \d+/i)
    })
  })

  it('shows the eligibility section with a populated pool', () => {
    renderPool()

    expect(screen.getByText(/in play/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /die face/i }).length).toBeGreaterThan(0)
  })

  it('signals the whole-queue shuffle as a destructive action (#3261)', () => {
    renderPool()

    const shuffle = screen.getByRole('button', { name: /shuffle queue/i })
    expect(shuffle.className).toContain('var(--theme-danger)')
    expect(shuffle).toHaveAccessibleDescription(/randomizes the complete active queue/i)
  })

  it('never displays retired blocked, stale or out-of-pool diagnostic panels', () => {
    renderPool()

    expect(screen.getAllByRole('button', { name: /die face/i })).toHaveLength(2)
    for (const text of [
      /series waiting for earlier issues/i,
      /series you haven't opened recently/i,
      /series out of the roll pool/i,
      /load more/i,
    ]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
  })

  it('renders the empty-state when there is nothing to roll', () => {
    renderPool({ pool: [] })

    expect(screen.getByText(/Nothing to roll yet/i)).toBeInTheDocument()
  })

  it('shows skipped threads when expanded and calls onUnskip', () => {
    const onUnskip = vi.fn()

    renderPool({
      pool: [],
      skippedThreads: [{ id: 10, title: 'Skipped Saga', format: 'Comic' }],
      skippedExpanded: true,
      onUnskip,
    })

    expect(screen.getByText('Skipped Saga')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /unskip this comic/i }))
    expect(onUnskip).toHaveBeenCalledWith(10)
  })

  it('hides skipped threads when collapsed and toggles expansion', () => {
    const onToggleSkipped = vi.fn()

    renderPool({
      pool: [],
      skippedThreads: [{ id: 10, title: 'Skipped Saga', format: 'Comic' }],
      skippedExpanded: false,
      onToggleSkipped,
    })

    expect(screen.queryByText('Skipped Saga')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText(/Skipped \(1\)/i))
    expect(onToggleSkipped).toHaveBeenCalledTimes(1)
  })

  it('renders each die face with its visible thread tags (#3425)', () => {
    renderPool({
      pool: [
        {
          id: 11,
          title: 'Amazing Spider-Man',
          format: 'Mainline',
          route_labels: [],
          tags: [
            {
              id: 4,
              name: 'Physical',
              normalized_name: 'physical',
              scope: 'global',
              owner_user_id: null,
              color: '#3B82F6',
              created_at: '2024-01-01T00:00:00.000Z',
              updated_at: '2024-01-01T00:00:00.000Z',
            },
          ],
        },
        { id: 12, title: 'Batman', format: 'DC', route_labels: [] },
      ],
    })

    expect(
      screen.getByRole('region', { name: 'Tags for Amazing Spider-Man' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(
      screen.queryByRole('region', { name: 'Tags for Batman' }),
    ).not.toBeInTheDocument()
  })

  it('announces die face tags to assistive technology', () => {
    renderPool({
      pool: [
        {
          id: 11,
          title: 'Amazing Spider-Man',
          format: 'Mainline',
          route_labels: [],
          tags: [
            {
              id: 4,
              name: 'Physical',
              normalized_name: 'physical',
              scope: 'global',
              owner_user_id: null,
              color: '#3B82F6',
              created_at: '2024-01-01T00:00:00.000Z',
              updated_at: '2024-01-01T00:00:00.000Z',
            },
            {
              id: 5,
              name: 'Annual',
              normalized_name: 'annual',
              scope: 'private',
              owner_user_id: 7,
              color: '#DC2626',
              created_at: '2024-01-01T00:00:00.000Z',
              updated_at: '2024-01-01T00:00:00.000Z',
            },
          ],
        },
      ],
    })

    expect(
      screen.getByRole('button', {
        name: /Die face 1: Amazing Spider-Man, tagged Physical, Annual\. Open series actions\./,
      }),
    ).toBeInTheDocument()
  })

  it('explains an all-blocked library instead of claiming the queue is empty', () => {
    renderPool({ pool: [], emptyPoolReason: 'all_blocked' })

    expect(screen.getByText(/series are waiting on earlier issues/i)).toBeInTheDocument()
    expect(screen.getByText(/blocked by an earlier issue/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
    expect(screen.queryByText(/Nothing to roll yet/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/reading queue is empty/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add a Series/i })).not.toBeInTheDocument()
  })

  it('explains an all-completed library with an add-series action', () => {
    renderPool({ pool: [], emptyPoolReason: 'all_completed' })

    expect(screen.getByText(/every series is completed/i)).toBeInTheDocument()
    expect(screen.getByText(/read every issue in your queue/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add a Series/i })).toBeInTheDocument()
    expect(screen.queryByText(/Nothing to roll yet/i)).not.toBeInTheDocument()
  })

  it('explains an all-out-of-pool library with a queue action', () => {
    renderPool({ pool: [], emptyPoolReason: 'all_out_of_pool' })

    expect(screen.getByText(/no series are in play/i)).toBeInTheDocument()
    expect(screen.getByText(/not in the active queue or are excluded/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
    expect(screen.queryByText(/Nothing to roll yet/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/series waiting for earlier issues/i)).not.toBeInTheDocument()
  })

  it('keeps the true empty queue state for a library with no series', () => {
    renderPool({ pool: [], emptyPoolReason: 'no_series' })

    expect(screen.getByText(/Nothing to roll yet/i)).toBeInTheDocument()
    expect(screen.getByText(/reading queue is empty/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add a Series/i })).toBeInTheDocument()
  })

  it('prefers a truthful empty-pool reason over the snoozed fallback', () => {
    renderPool({
      pool: [],
      emptyPoolReason: 'all_completed',
      snoozedThreads: [{ id: 2, title: 'Paused', format: 'Comic' }],
    })

    expect(screen.getByText(/every series is completed/i)).toBeInTheDocument()
    expect(screen.queryByText(/Every series is snoozed/i)).not.toBeInTheDocument()
  })
})
