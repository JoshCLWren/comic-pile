import { render, screen, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread } from '../../types/rollBootstrap'

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
const mockBlockingReasonMap: Record<number, string[]> = {}
const mockSnoozedThreads: Array<{ id: number; title: string; format: string }> = []

function renderPool(overrides: Partial<{
  pool: RollBootstrapThread[]
  blockedThreads: RollBootstrapThread[]
  blockingReasonMap: Record<number, string[]>
  blockedExpanded: boolean
}> = {}) {
  const {
    pool = mockPool,
    blockedThreads = mockBlockedThreads,
    blockingReasonMap = mockBlockingReasonMap,
    blockedExpanded = false,
  } = overrides

  return render(
    <MemoryRouter>
      <ThreadPool
        pool={pool}
        blockedThreads={blockedThreads}
        blockingReasonMap={blockingReasonMap}
        dieSize={20}
        isRatingView={false}
        isRolling={false}
        rolledResult={null}
        selectedThreadId={null}
        staleThread={null}
        staleThreadCount={0}
        snoozedThreads={mockSnoozedThreads}
        snoozedExpanded={false}
        blockedExpanded={blockedExpanded}
        onThreadClick={() => {}}
        onUnsnooze={() => {}}
        onReadStale={() => {}}
        onToggleSnoozed={() => {}}
        onToggleBlocked={() => {}}
        onShuffle={() => {}}
        unsnoozeIsPending={false}
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
      expect(label).toMatch(/connected to/i)
      expect(label).not.toMatch(/\broutes\b/i)
      expect(element.textContent).toMatch(/The Amazing Spider-Man|Batman/)
      expect(element).not.toHaveTextContent(/Issue \d+/i)
    })
  })

  it('shows the eligibility section with a populated pool', () => {
    renderPool()

    expect(screen.getByText(/Eligible now/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /die face/i }).length).toBeGreaterThan(0)
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
      blockingReasonMap: { 3: ['dependency'] },
    })
    // Inject the spy by re-rendering with the handler.
    rerender(
      <MemoryRouter>
        <ThreadPool
          pool={mockPool}
          blockedThreads={[blockedThread]}
          blockingReasonMap={{ 3: ['dependency'] }}
          dieSize={20}
          isRatingView={false}
          isRolling={false}
          rolledResult={null}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={mockSnoozedThreads}
          snoozedExpanded={false}
          blockedExpanded={false}
          onThreadClick={() => {}}
          onUnsnooze={() => {}}
          onReadStale={() => {}}
          onToggleSnoozed={() => {}}
          onToggleBlocked={onToggleBlocked}
          onShuffle={() => {}}
          unsnoozeIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    const toggle = screen.getByText(/1 thread hidden \(blocked by dependencies\)/i)
    expect(toggle).toBeInTheDocument()
    // Blocked thread titles stay hidden until the section is expanded.
    expect(screen.queryByText('Blocked Thread')).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(onToggleBlocked).toHaveBeenCalledTimes(1)
  })

  it('renders the empty-state when there is nothing to roll', () => {
    renderPool({ pool: [], blockedThreads: [], blockingReasonMap: {} })

    expect(screen.getByText(/Nothing to roll yet/i)).toBeInTheDocument()
  })
})
