import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { BlockingDependency } from '../types'
import type { RollBootstrapThread, ThreadExclusionReason } from '../types/rollBootstrap'

function RouteProbe() {
  const location = useLocation()
  return <p data-testid="route">{location.pathname}</p>
}

function ThreadRoute() {
  const { id } = useParams()
  return <p data-testid="thread-content">Thread {id} content</p>
}

function renderPool(overrides: {
  inactiveThreads?: ThreadExclusionReason[]
  inactiveExpanded?: boolean
  blockedThreads?: RollBootstrapThread[]
  blockedExpanded?: boolean
  blockingDependencyMap?: Record<number, BlockingDependency[]>
  onToggleInactive?: () => void
  onThreadClick?: () => void
  onShuffle?: () => void
} = {}) {
  const {
    inactiveThreads = [],
    inactiveExpanded = false,
    blockedThreads = [],
    blockedExpanded = false,
    blockingDependencyMap = {},
    onToggleInactive = vi.fn(),
    onThreadClick = vi.fn(),
    onShuffle = vi.fn(),
  } = overrides

  return render(
    <MemoryRouter initialEntries={['/roll']}>
      <Routes>
        <Route
          path="/roll"
          element={(
            <ThreadPool
              pool={[]}
              blockedThreads={blockedThreads}
              blockingDependencyMap={blockingDependencyMap}
              dieSize={6}
              isRatingView={false}
              selectedThreadId={null}
              staleThread={null}
              staleThreadCount={0}
              snoozedThreads={[]}
              snoozedExpanded={false}
              skippedThreads={[]}
              skippedExpanded={false}
              blockedExpanded={blockedExpanded}
              staleExpanded={false}
              inactiveThreads={inactiveThreads}
              inactiveExpanded={inactiveExpanded}
              onThreadClick={onThreadClick}
              onUnsnooze={vi.fn()}
              onUnskip={vi.fn()}
              onReadStale={vi.fn()}
              onToggleSnoozed={vi.fn()}
              onToggleSkipped={vi.fn()}
              onToggleStale={vi.fn()}
              onToggleBlocked={vi.fn()}
              onToggleInactive={onToggleInactive}
              onShuffle={onShuffle}
              unsnoozeIsPending={false}
              unskipIsPending={false}
              shuffleIsPending={false}
            />
          )}
        />
        <Route path="/thread/:id" element={<ThreadRoute />} />
      </Routes>
      <RouteProbe />
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

  it('renders an expanded out-of-pool row without thread_id as plain text, not a link', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 2, title: 'Saga', format: 'Comic', reason: 'completed', detail: 'Read the full series' },
        { title: 'Orphaned Series', format: 'Comic', reason: 'not_in_queue', detail: 'No resolvable thread' },
      ],
      inactiveExpanded: true,
    })

    expect(screen.getByText('Orphaned Series')).toBeInTheDocument()
    expect(screen.getByText('No resolvable thread')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Orphaned Series' })).not.toBeInTheDocument()
    expect(screen.getByText('Orphaned Series').closest('a')).not.toBeInTheDocument()

    // Rows that still have a thread_id remain navigable links.
    expect(screen.getByRole('link', { name: 'Saga' })).toHaveAttribute('href', '/thread/2')
  })

  it('keeps blocked rows navigable with an id and honest without one', () => {
    renderPool({
      blockedExpanded: true,
      blockedThreads: [
        { id: 7, title: 'Monstress', format: 'Comic' },
        { id: 0, title: 'No Identifier', format: 'Comic' },
      ],
    })

    expect(screen.getByRole('link', { name: 'Monstress' })).toHaveAttribute('href', '/thread/7')
    expect(screen.queryByRole('link', { name: 'No Identifier' })).not.toBeInTheDocument()
    expect(screen.getByText('No Identifier').closest('a')).toBeNull()
  })

  it('reaches a blocked Thread with Tab + Enter and shows visible focus', async () => {
    const user = userEvent.setup()

    renderPool({
      blockedExpanded: true,
      blockedThreads: [{ id: 41, title: 'Monstress', format: 'Comic' }],
    })

    const link = screen.getByRole('link', { name: 'Monstress' })
    expect(link.className).toContain('focus-visible:ring-2')
    // The row title stays inside the row column instead of overflowing.
    expect(link.className).toContain('truncate')

    for (let step = 0; step < 3 && document.activeElement !== link; step += 1) {
      await user.tab()
    }
    expect(link).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(screen.getByTestId('route')).toHaveTextContent('/thread/41')
    expect(screen.getByTestId('thread-content')).toHaveTextContent('Thread 41 content')
  })

  it('keeps blocker links outside the row link and opens the dependency Thread', async () => {
    const user = userEvent.setup()

    renderPool({
      blockedExpanded: true,
      blockedThreads: [
        {
          id: 41,
          title: 'Monstress',
          format: 'Comic',
          blocking_reasons: ['Read Saga #1 first'],
        },
      ],
      blockingDependencyMap: {
        41: [
          {
            thread_id: 77,
            thread_title: 'Saga',
            issue_id: 5,
            issue_number: '1',
            label: 'Read Saga #1 first',
          },
        ],
      },
    })

    const rowLink = screen.getByRole('link', { name: 'Monstress' })
    const blockerLink = screen.getByRole('link', { name: 'Open Saga issue #1' })
    // The dependency link is a sibling of the row link, never nested inside it.
    expect(rowLink.contains(blockerLink)).toBe(false)
    expect(rowLink.closest('a')).toBe(rowLink)
    expect(blockerLink.closest('a')).toBe(blockerLink)
    expect(blockerLink).toHaveAttribute('href', '/thread/77?issue=5#issue-5')

    await user.click(blockerLink)

    expect(screen.getByTestId('route')).toHaveTextContent('/thread/77')
    expect(screen.getByTestId('thread-content')).toHaveTextContent('Thread 77 content')
  })

  it('keeps the Superman regression rows linked to their own Threads', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 11, title: 'Superman', format: 'Comic', reason: 'completed', detail: 'Read the full series' },
        { thread_id: 12, title: 'Superman', format: 'Comic', reason: 'not_in_queue', detail: 'Waiting for a later session' },
      ],
      inactiveExpanded: true,
    })

    const links = screen.getAllByRole('link', { name: /^Superman/ })
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/thread/11', '/thread/12'])
    // Same-named rows carry a truthful Thread fallback instead of a guessed volume.
    expect(links[0]).toHaveTextContent('Series #11')
    expect(links[1]).toHaveTextContent('Series #12')
  })

  it('never loans a same-title Thread to a row that has no id', () => {
    renderPool({
      inactiveThreads: [
        { thread_id: 11, title: 'Superman', format: 'Comic', reason: 'completed' },
        { title: 'Superman', format: 'Comic', reason: 'not_in_queue' },
      ],
      inactiveExpanded: true,
    })

    const links = screen.getAllByRole('link', { name: /^Superman/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/thread/11')
    expect(screen.getAllByText('Superman')).toHaveLength(2)
  })

  it('opens the exact Thread by pointer without firing Roll actions', async () => {
    const user = userEvent.setup()
    const onThreadClick = vi.fn()
    const onShuffle = vi.fn()

    renderPool({
      inactiveThreads: [
        { thread_id: 21, title: 'Saga', format: 'Comic', reason: 'completed' },
      ],
      inactiveExpanded: true,
      onThreadClick,
      onShuffle,
    })

    await user.click(screen.getByRole('link', { name: 'Saga' }))

    expect(screen.getByTestId('route')).toHaveTextContent('/thread/21')
    expect(screen.getByTestId('thread-content')).toHaveTextContent('Thread 21 content')
    expect(onThreadClick).not.toHaveBeenCalled()
    expect(onShuffle).not.toHaveBeenCalled()
  })

  it('reaches the exact Thread with Tab + Enter and shows visible focus', async () => {
    const user = userEvent.setup()

    renderPool({
      inactiveThreads: [
        { thread_id: 31, title: 'X-Men', format: 'Comic', reason: 'not_in_queue' },
      ],
      inactiveExpanded: true,
    })

    const link = screen.getByRole('link', { name: 'X-Men' })
    expect(link.className).toContain('focus-visible:ring-2')
    // Narrow layouts keep the row inside the column instead of overflowing.
    expect(link.className).toContain('flex-1')
    expect(link.className).toContain('min-w-0')
    expect(link.className).toContain('truncate')

    // Walk the section's tab stops until the row link owns focus.
    for (let step = 0; step < 3 && document.activeElement !== link; step += 1) {
      await user.tab()
    }
    expect(link).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(screen.getByTestId('route')).toHaveTextContent('/thread/31')
    expect(screen.getByTestId('thread-content')).toHaveTextContent('Thread 31 content')
  })
})
