import { render, screen, fireEvent } from '@testing-library/react'
import type { BlockingDependency } from '../types'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread } from '../types/rollBootstrap'

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

const mockBlockedThreads: RollBootstrapThread[] = []
const mockBlockingDependencyMap: Record<number, BlockingDependency[]> = {}
const mockSnoozedThreads: Array<{ id: number; title: string; format: string }> = []
const mockSkippedThreads: Array<{ id: number; title: string; format: string }> = []

function renderPool(overrides: Partial<{
  pool: RollBootstrapThread[]
  blockedThreads: RollBootstrapThread[]
  blockingDependencyMap: Record<number, BlockingDependency[]>
  blockedExpanded: boolean
}> = {}) {
  const {
    pool = mockPool,
    blockedThreads = mockBlockedThreads,
    blockingDependencyMap = mockBlockingDependencyMap,
    blockedExpanded = false,
  } = overrides

  return render(
    <MemoryRouter>
      <ThreadPool
        pool={pool}
        blockedThreads={blockedThreads}
        blockingDependencyMap={blockingDependencyMap}
        dieSize={20}
        isRatingView={false}
        selectedThreadId={null}
        staleThread={null}
        staleThreadCount={0}
        snoozedThreads={mockSnoozedThreads}
        snoozedExpanded={false}
        skippedThreads={mockSkippedThreads}
        skippedExpanded={false}
        blockedExpanded={blockedExpanded}
        staleExpanded={false}
        onThreadClick={() => {}}
        onUnsnooze={() => {}}
        onUnskip={() => {}}
        onReadStale={() => {}}
        onToggleSnoozed={() => {}}
        onToggleSkipped={() => {}}
        onToggleStale={() => {}}
        onToggleBlocked={() => {}}
        onShuffle={() => {}}
        unsnoozeIsPending={false}
        unskipIsPending={false}
        shuffleIsPending={false}
      />
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
      expect(label).toMatch(/groups Main Story/i)
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

  it('collapses blocked threads and exposes a toggle', () => {
    const onToggleBlocked = vi.fn()
    const blockedThread: RollBootstrapThread = {
      id: 3,
      title: 'Blocked Thread',
      format: 'Mainline',
      issue_number: '1',
      route_labels: ['Blocked'],
    }

    const { rerender } = renderPool({
      pool: mockPool,
      blockedThreads: [blockedThread],
      blockingDependencyMap: { 3: [{ thread_id: 3, thread_title: 'Dependency Thread', issue_number: '9', label: 'dependency' }] },
    })
    // Inject the spy by re-rendering with the handler.
    rerender(
      <MemoryRouter>
        <ThreadPool
          pool={mockPool}
          blockedThreads={[blockedThread]}
          blockingDependencyMap={{ 3: [{ thread_id: 3, thread_title: 'Dependency Thread', issue_number: '9', label: 'dependency' }] }}
          dieSize={20}
          isRatingView={false}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={mockSnoozedThreads}
          snoozedExpanded={false}
          skippedThreads={mockSkippedThreads}
          skippedExpanded={false}
          blockedExpanded={false}
          staleExpanded={false}
          onThreadClick={() => {}}
          onUnsnooze={() => {}}
          onUnskip={() => {}}
          onReadStale={() => {}}
          onToggleSnoozed={() => {}}
          onToggleSkipped={() => {}}
          onToggleStale={() => {}}
          onToggleBlocked={onToggleBlocked}
          onShuffle={() => {}}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    const toggle = screen.getByText(/1 series waiting for earlier issues/i)
    expect(toggle).toBeInTheDocument()
    // Blocked thread titles stay hidden until the section is expanded.
    expect(screen.queryByText('Blocked Thread')).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(onToggleBlocked).toHaveBeenCalledTimes(1)
  })

  it('renders the empty-state when there is nothing to roll', () => {
    renderPool({ pool: [], blockedThreads: [], blockingDependencyMap: {} })

    expect(screen.getByText(/Nothing to roll yet/i)).toBeInTheDocument()
  })

  it('shows skipped threads when expanded and calls onUnskip', () => {
    const onUnskip = vi.fn()
    const onToggleSkipped = vi.fn()

    render(
      <MemoryRouter>
        <ThreadPool
          pool={[]}
          blockedThreads={[]}
          blockingDependencyMap={{}}
          dieSize={6}
          isRatingView={false}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={[]}
          snoozedExpanded={false}
          skippedThreads={[{ id: 10, title: 'Skipped Saga', format: 'Comic' }]}
          skippedExpanded={true}
          blockedExpanded={false}
          staleExpanded={false}
          onThreadClick={() => {}}
          onUnsnooze={() => {}}
          onUnskip={onUnskip}
          onReadStale={() => {}}
          onToggleSnoozed={() => {}}
          onToggleSkipped={onToggleSkipped}
          onToggleStale={() => {}}
          onToggleBlocked={() => {}}
          onShuffle={() => {}}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Skipped Saga')).toBeInTheDocument()
    const unskipBtn = screen.getByRole('button', { name: /unskip this comic/i })
    fireEvent.click(unskipBtn)
    expect(onUnskip).toHaveBeenCalledWith(10)
  })

  it('hides skipped threads when collapsed and toggles expansion', () => {
    const onToggleSkipped = vi.fn()

    render(
      <MemoryRouter>
        <ThreadPool
          pool={[]}
          blockedThreads={[]}
          blockingDependencyMap={{}}
          dieSize={6}
          isRatingView={false}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={[]}
          snoozedExpanded={false}
          skippedThreads={[{ id: 10, title: 'Skipped Saga', format: 'Comic' }]}
          skippedExpanded={false}
          blockedExpanded={false}
          staleExpanded={false}
          onThreadClick={() => {}}
          onUnsnooze={() => {}}
          onUnskip={() => {}}
          onReadStale={() => {}}
          onToggleSnoozed={() => {}}
          onToggleSkipped={onToggleSkipped}
          onToggleStale={vi.fn()}
          onToggleBlocked={() => {}}
          onShuffle={() => {}}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByText('Skipped Saga')).not.toBeInTheDocument()
    const toggle = screen.getByText(/Skipped \(1\)/i)
    fireEvent.click(toggle)
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
        name: /Die face 1: Amazing Spider-Man, Mainline, tagged Physical, Annual\. Open series actions\./,
      }),
    ).toBeInTheDocument()
  })
})
