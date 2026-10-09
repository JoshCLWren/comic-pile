import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { ThreadExclusionReason } from '../types/rollBootstrap'

function renderPool(overrides: {
  inactiveThreads?: ThreadExclusionReason[]
  inactiveExpanded?: boolean
  onToggleInactive?: () => void
} = {}) {
  const {
    inactiveThreads = [],
    inactiveExpanded = false,
    onToggleInactive = vi.fn(),
  } = overrides

  return render(
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
        skippedThreads={[]}
        skippedExpanded={false}
        blockedExpanded={false}
        staleExpanded={false}
        inactiveThreads={inactiveThreads}
        inactiveExpanded={inactiveExpanded}
        onThreadClick={vi.fn()}
        onUnsnooze={vi.fn()}
        onUnskip={vi.fn()}
        onReadStale={vi.fn()}
        onToggleSnoozed={vi.fn()}
        onToggleSkipped={vi.fn()}
        onToggleStale={vi.fn()}
        onToggleBlocked={vi.fn()}
        onToggleInactive={onToggleInactive}
        onShuffle={vi.fn()}
        unsnoozeIsPending={false}
        unskipIsPending={false}
        shuffleIsPending={false}
      />
    </MemoryRouter>,
  )
}

describe('ThreadPool exclusion transparency', () => {
  it('explains series excluded from the roll pool once expanded', () => {
    const onToggleInactive = vi.fn()
    const { rerender } = renderPool({
      inactiveThreads: [
        { thread_id: 2, title: 'Saga', format: 'Comic', reason: 'completed', detail: 'Read the full series' },
        { thread_id: 3, title: 'Order Test Beta', format: 'Comic', reason: 'not_in_queue', detail: 'Not in the active queue' },
      ],
      onToggleInactive,
    })

    const toggle = screen.getByText(/2 series out of the roll pool/i)
    expect(toggle).toBeInTheDocument()
    expect(toggle.closest('button')).toHaveAttribute('aria-expanded', 'false')
    // Titles and reasons stay hidden until the section is expanded.
    expect(screen.queryByText('Saga')).not.toBeInTheDocument()

    fireEvent.click(toggle)
    expect(onToggleInactive).toHaveBeenCalledTimes(1)

    rerender(
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
          skippedThreads={[]}
          skippedExpanded={false}
          blockedExpanded={false}
          staleExpanded={false}
          inactiveThreads={[
            { thread_id: 2, title: 'Saga', format: 'Comic', reason: 'completed', detail: 'Read the full series' },
            { thread_id: 3, title: 'Order Test Beta', format: 'Comic', reason: 'not_in_queue', detail: 'Not in the active queue' },
          ]}
          inactiveExpanded
          onThreadClick={vi.fn()}
          onUnsnooze={vi.fn()}
          onUnskip={vi.fn()}
          onReadStale={vi.fn()}
          onToggleSnoozed={vi.fn()}
          onToggleSkipped={vi.fn()}
          onToggleStale={vi.fn()}
          onToggleBlocked={vi.fn()}
          onToggleInactive={vi.fn()}
          onShuffle={vi.fn()}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText('Read the full series')).toBeInTheDocument()
    expect(screen.getByText('Order Test Beta')).toBeInTheDocument()
    expect(screen.getByText('Not in the active queue')).toBeInTheDocument()
  })

  it('falls back to a readable label when the API sends no detail', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 4, title: 'Weird Input Test', format: 'Comic', reason: 'snoozed' },
      ],
      inactiveExpanded: true,
    })

    expect(screen.getByText('Weird Input Test')).toBeInTheDocument()
    expect(screen.getByText('Snoozed')).toBeInTheDocument()
  })

  it('never renders raw reason codes', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 5, title: 'Saga', format: 'Comic', reason: 'not_in_queue' },
      ],
      inactiveExpanded: true,
    })

    expect(screen.queryByText('not_in_queue')).not.toBeInTheDocument()
    expect(screen.getByText('Not in the active queue')).toBeInTheDocument()
  })

  it('replaces the empty state when only inactive series remain', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 6, title: 'Saga', format: 'Comic', reason: 'completed', detail: 'Read the full series' },
      ],
    })

    expect(screen.queryByText(/Nothing to roll yet/i)).not.toBeInTheDocument()
    expect(screen.getByText(/No series in play right now/i)).toBeInTheDocument()
  })
})