import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentProps } from 'react'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

type ThreadPoolProps = ComponentProps<typeof ThreadPool>

const baseProps = {
  pool: [{ id: 1, title: 'Saga', format: 'Comic' }],
  blockedThreads: [],
  blockingDependencyMap: {},
  dieSize: 6,
  isRatingView: false,
  selectedThreadId: null,
  staleThread: null,
  staleThreadCount: 0,
  snoozedThreads: [],
  snoozedExpanded: false,
  skippedThreads: [],
  skippedExpanded: false,
  blockedExpanded: false,
  onThreadClick: vi.fn(),
  onUnsnooze: vi.fn(),
  onUnskip: vi.fn(),
  onReadStale: vi.fn(),
  onToggleSnoozed: vi.fn(),
  onToggleSkipped: vi.fn(),
  onToggleBlocked: vi.fn(),
  onShuffle: vi.fn(),
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

describe('ThreadPool exclusion explanations (issue #3125)', () => {
  it('stays silent when nothing is excluded from the roll', () => {
    renderPool()

    expect(screen.queryByTestId('roll-excluded-summary')).not.toBeInTheDocument()
  })

  it('names every excluded series with its reason', () => {
    renderPool({
      pool: [
        { id: 1, title: 'Saga', format: 'Comic' },
        { id: 2, title: 'Monstress', format: 'Comic' },
      ],
      blockedThreads: [{ id: 3, title: 'Order Test Beta', format: 'Comic' }],
      blockedCount: 1,
      snoozedThreads: [{ id: 4, title: 'Weird Input Test', format: 'Comic' }],
      snoozedCount: 1,
      snoozedBackoffThreads: [{ id: 5, title: 'Backoff Series', format: 'Comic' }],
      snoozedBackoffCount: 1,
      skippedThreads: [{ id: 6, title: 'Skipped Series', format: 'Comic' }],
      poolOverflowCount: 20,
    })

    const summary = screen.getByTestId('roll-excluded-summary')
    // 1 blocked + 2 snoozed + 1 skipped + 20 behind the die.
    expect(summary).toHaveTextContent('24 excluded from this roll')
    expect(summary).toHaveTextContent('1 waiting on an earlier issue')
    expect(summary).toHaveTextContent('2 snoozed')
    expect(summary).toHaveTextContent('1 skipped this session')
    expect(summary).toHaveTextContent('20 behind the die')
  })

  it('keeps the authoritative backend counts when the listed series are bounded', () => {
    renderPool({
      blockedThreads: [{ id: 3, title: 'Blocked A', format: 'Comic' }],
      blockedCount: 12,
      snoozedThreads: [{ id: 4, title: 'Snoozed A', format: 'Comic' }],
      snoozedCount: 5,
      snoozedBackoffThreads: [{ id: 5, title: 'Backoff A', format: 'Comic' }],
      snoozedBackoffCount: 2,
    })

    expect(screen.getByText(/12 series waiting for earlier issues/i)).toBeInTheDocument()
    expect(screen.getByText(/\+11 more/i)).toBeInTheDocument()
    expect(screen.getByText(/Snoozed \(7\)/i)).toBeInTheDocument()
  })

  it('lists a backoff-snoozed series with a reason instead of an unsnooze action', () => {
    renderPool({
      snoozedThreads: [{ id: 4, title: 'Session Snooze', format: 'Comic' }],
      snoozedCount: 1,
      snoozedBackoffThreads: [{ id: 5, title: 'Backoff Series', format: 'Comic' }],
      snoozedBackoffCount: 1,
      snoozedExpanded: true,
    })

    expect(screen.getByText('Session Snooze')).toBeInTheDocument()
    expect(screen.getByText('Backoff Series')).toBeInTheDocument()
    expect(screen.getByText(/Snoozed in an earlier session/i)).toBeInTheDocument()
    // The session-scoped unsnooze action must not be offered for a backoff series.
    expect(screen.getAllByRole('button', { name: /unsnooze this comic/i })).toHaveLength(1)
  })

  it('reports series the reader cannot act on directly', () => {
    renderPool({
      snoozedBackoffThreads: [{ id: 5, title: 'Backoff Series', format: 'Comic' }],
      snoozedBackoffCount: 1,
    })

    expect(screen.getByText(/Snoozed \(1\)/i)).toBeInTheDocument()
    expect(screen.getByTestId('roll-excluded-summary')).toHaveTextContent('1 snoozed')
  })

  it('explains an all-backoff queue instead of claiming there is nothing to roll', () => {
    renderPool({
      pool: [],
      blockedThreads: [],
      snoozedThreads: [],
      snoozedBackoffThreads: [{ id: 5, title: 'Backoff Series', format: 'Comic' }],
      snoozedBackoffCount: 1,
    })

    expect(screen.queryByText(/Nothing to roll yet/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Every series is blocked or snoozed/i)).toBeInTheDocument()
  })

  it('hides every exclusion surface while rating', () => {
    renderPool({
      isRatingView: true,
      blockedThreads: [{ id: 3, title: 'Blocked A', format: 'Comic' }],
      blockedCount: 1,
      poolOverflowCount: 4,
    })

    expect(screen.queryByTestId('roll-excluded-summary')).not.toBeInTheDocument()
    expect(screen.queryByText(/series waiting for earlier issues/i)).not.toBeInTheDocument()
  })
})