import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread, ThreadExclusionReason } from '../types/rollBootstrap'

const previewBlocked: RollBootstrapThread = {
  id: 1,
  title: 'Preview blocked',
  format: 'Comic',
}

const previewInactive: ThreadExclusionReason = {
  thread_id: 2,
  title: 'Preview inactive',
  format: 'Comic',
  reason: 'completed',
  detail: 'Read the full series',
}

function renderPool(overrides: {
  blockedThreads?: RollBootstrapThread[]
  blockedCount?: number
  blockedHasMore?: boolean
  blockedExpanded?: boolean
  blockedLoadError?: boolean
  onLoadMoreBlocked?: () => void
  inactiveThreads?: ThreadExclusionReason[]
  inactiveCount?: number
  inactiveHasMore?: boolean
  inactiveExpanded?: boolean
  inactiveLoadError?: boolean
  onLoadMoreInactive?: () => void
} = {}) {
  return render(
    <MemoryRouter>
      <ThreadPool
        pool={[]}
        blockedThreads={overrides.blockedThreads ?? []}
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
        blockedExpanded={overrides.blockedExpanded ?? false}
        staleExpanded={false}
        blockedCount={overrides.blockedCount}
        blockedHasMore={overrides.blockedHasMore}
        blockedLoadError={overrides.blockedLoadError}
        onLoadMoreBlocked={overrides.onLoadMoreBlocked}
        inactiveThreads={overrides.inactiveThreads ?? []}
        inactiveExpanded={overrides.inactiveExpanded ?? false}
        inactiveCount={overrides.inactiveCount}
        inactiveHasMore={overrides.inactiveHasMore}
        inactiveLoadError={overrides.inactiveLoadError}
        onLoadMoreInactive={overrides.onLoadMoreInactive}
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
}

describe('ThreadPool accurate category totals (#3330)', () => {
  it('reports the blocked total instead of the preview length', () => {
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 25,
      blockedExpanded: true,
    })

    expect(screen.getByText('25 series waiting for earlier issues')).toBeInTheDocument()
    expect(screen.queryByText('1 series waiting for earlier issues')).not.toBeInTheDocument()
    expect(screen.getByText('Preview blocked')).toBeInTheDocument()
  })

  it('reports the inactive total instead of the preview length', () => {
    renderPool({
      inactiveThreads: [previewInactive],
      inactiveCount: 30,
      inactiveExpanded: true,
    })

    expect(screen.getByText('30 series out of the roll pool')).toBeInTheDocument()
    expect(screen.queryByText('1 series out of the roll pool')).not.toBeInTheDocument()
    expect(screen.getByText('Preview inactive')).toBeInTheDocument()
  })

  it('offers a load-more control that reaches the remaining blocked records', () => {
    const onLoadMoreBlocked = vi.fn()
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 25,
      blockedHasMore: true,
      blockedExpanded: true,
      onLoadMoreBlocked,
    })

    const loadMore = screen.getByRole('button', { name: /load more \(24 remaining\)/i })
    fireEvent.click(loadMore)

    expect(onLoadMoreBlocked).toHaveBeenCalledTimes(1)
  })

  it('offers a load-more control that reaches the remaining inactive records', () => {
    const onLoadMoreInactive = vi.fn()
    renderPool({
      inactiveThreads: [previewInactive],
      inactiveCount: 30,
      inactiveHasMore: true,
      inactiveExpanded: true,
      onLoadMoreInactive,
    })

    const loadMore = screen.getByRole('button', { name: /load more \(29 remaining\)/i })
    fireEvent.click(loadMore)

    expect(onLoadMoreInactive).toHaveBeenCalledTimes(1)
  })

  it('hides the load-more control once every counted record is rendered', () => {
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 1,
      blockedHasMore: false,
      blockedExpanded: true,
      onLoadMoreBlocked: vi.fn(),
    })

    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()
  })

  it('states how many of the counted series are rendered while the list is truncated', () => {
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 25,
      blockedHasMore: true,
      blockedExpanded: true,
      onLoadMoreBlocked: vi.fn(),
    })

    expect(screen.getByText('Showing 1 of 25 series.')).toBeInTheDocument()
  })

  it('offers a working retry when a blocked page failed to load', () => {
    const onLoadMoreBlocked = vi.fn()
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 25,
      blockedHasMore: true,
      blockedExpanded: true,
      blockedLoadError: true,
      onLoadMoreBlocked,
    })

    expect(
      screen.getByText(/could not load more blocked series/i),
    ).toBeInTheDocument()

    const retry = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retry)

    expect(onLoadMoreBlocked).toHaveBeenCalledTimes(1)
  })

  it('offers a working retry when an inactive page failed to load', () => {
    const onLoadMoreInactive = vi.fn()
    renderPool({
      inactiveThreads: [previewInactive],
      inactiveCount: 30,
      inactiveHasMore: true,
      inactiveExpanded: true,
      inactiveLoadError: true,
      onLoadMoreInactive,
    })

    expect(
      screen.getByText(/could not load more out-of-pool series/i),
    ).toBeInTheDocument()

    const retry = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retry)

    expect(onLoadMoreInactive).toHaveBeenCalledTimes(1)
  })

  it('styles the load-more controls with semantic theme roles and ordinary button typography', () => {
    renderPool({
      blockedThreads: [previewBlocked],
      blockedCount: 25,
      blockedHasMore: true,
      blockedExpanded: true,
      onLoadMoreBlocked: vi.fn(),
    })

    const loadMore = screen.getByRole('button', { name: /load more \(24 remaining\)/i })
    const className = loadMore.getAttribute('class') ?? ''

    expect(className).toContain('var(--theme-bg-panel)')
    expect(className).toContain('var(--theme-border)')
    expect(className).toContain('var(--theme-text-primary)')
    expect(className).not.toContain('stone')
    expect(className).not.toContain('uppercase')
    expect(className).not.toContain('tracking-widest')
  })
})
