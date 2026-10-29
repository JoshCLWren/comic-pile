import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RollPoolRow } from '../pages/RollPage/components/RollPoolRow'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import { rollProgressCopy } from '../pages/RollPage/rollPoolRowCopy'
import type { RollPoolRow as RollPoolRowModel } from '../types/rollBootstrap'

function makeRow(overrides: Partial<RollPoolRowModel> = {}): RollPoolRowModel {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    issue_id: 101,
    issue_number: '12',
    cover_url: 'https://images.example/saga-12.jpg',
    canonical_series_title: 'Saga',
    identity_state: 'confirmed',
    series_mapping_state: 'confirmed',
    latest_rating: 4.5,
    average_rating: 4.1,
    rating_count: 7,
    read_count: 8,
    issue_count: 27,
    progress_scope: 'canonical_series_run',
    routes: [{ kind: 'group', name: 'Earth-616 reading plan' }],
    overflow_routes_count: 0,
    ...overrides,
  }
}

function renderRow(row: RollPoolRowModel) {
  return render(
    <RollPoolRow row={row} dieFace={1} isSelected={false} onClick={vi.fn()} />,
  )
}

describe('RollPoolRow', () => {
  it('renders cover, identity, issue number, format, ratings, run progress, and groups', () => {
    renderRow(makeRow())

    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText('#12')).toBeInTheDocument()
    expect(screen.getByText(/^Comic/)).toBeInTheDocument()
    expect(screen.getByTestId('roll-pool-cover')).toHaveAttribute(
      'src',
      'https://images.example/saga-12.jpg',
    )
    expect(screen.getByTestId('roll-pool-ratings')).toHaveTextContent('Latest 4.5 · Avg 4.1 from 7')
    expect(screen.getByTestId('roll-pool-progress')).toHaveTextContent('8 of 27 read')
    expect(screen.getByTestId('roll-pool-groups')).toHaveTextContent(
      'Groups · Earth-616 reading plan',
    )
    expect(screen.queryByTestId('roll-pool-identity-status')).not.toBeInTheDocument()
  })

  it('shows unresolved identity as status only with no Map series control', () => {
    renderRow(
      makeRow({
        identity_state: 'unresolved',
        series_mapping_state: 'unresolved',
        canonical_series_title: null,
        latest_rating: null,
        average_rating: null,
        rating_count: 0,
        cover_url: null,
      }),
    )

    expect(screen.getByTestId('roll-pool-identity-status')).toHaveTextContent('Identity unresolved')
    expect(screen.queryByRole('button', { name: /map series/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('roll-pool-ratings')).not.toBeInTheDocument()
  })

  it('renders honest fallbacks when the cover, format, and canonical title are missing', () => {
    renderRow(makeRow({ cover_url: null, format: '', canonical_series_title: null }))

    expect(screen.getByTestId('roll-pool-cover-placeholder')).toBeInTheDocument()
    expect(screen.queryByTestId('roll-pool-cover')).not.toBeInTheDocument()
    expect(screen.getByText('Format unknown')).toBeInTheDocument()
  })

  it('does not invent a run-length denominator when issue_count is null', () => {
    renderRow(makeRow({ issue_count: null, read_count: 8 }))

    const progress = screen.getByTestId('roll-pool-progress')
    expect(progress).toHaveTextContent('8 read')
    expect(progress.textContent).not.toContain('of')
    expect(progress.textContent).not.toContain('%')
  })

  it('labels thread-scoped progress as thread progress', () => {
    renderRow(
      makeRow({
        progress_scope: 'thread',
        read_count: 3,
        issue_count: 9,
        latest_rating: null,
        average_rating: null,
        rating_count: 0,
      }),
    )

    expect(screen.getByTestId('roll-pool-progress')).toHaveTextContent(
      'Thread progress · 3 of 9 read',
    )
  })

  it('keeps a long title usable without losing the full value', () => {
    const longTitle = `The Uncanny ${'Extremely '.repeat(12)}Long Running Series Title`
    renderRow(makeRow({ title: longTitle, canonical_series_title: longTitle }))

    const title = screen.getByText(longTitle)
    expect(title).toHaveAttribute('title', longTitle)
  })

  it('remains useful when every decorative field is null', () => {
    renderRow({
      id: 4,
      title: 'Bare Minimum',
      format: 'Comic',
      issue_number: null,
      cover_url: null,
      canonical_series_title: null,
      identity_state: 'unresolved',
      latest_rating: null,
      average_rating: null,
      rating_count: null,
      read_count: null,
      issue_count: null,
      progress_scope: null,
      routes: [],
    })

    expect(screen.getByText('Bare Minimum')).toBeInTheDocument()
    expect(screen.getByText('Next unread issue')).toBeInTheDocument()
    expect(screen.queryByTestId('roll-pool-progress')).not.toBeInTheDocument()
    expect(screen.queryByTestId('roll-pool-groups')).not.toBeInTheDocument()
  })
})

describe('rollProgressCopy', () => {
  it('uses the full stored run length as the canonical denominator', () => {
    expect(rollProgressCopy(makeRow({ read_count: 8, issue_count: 27 }))).toBe('8 of 27 read')
  })

  it('returns null when neither side of progress is known', () => {
    expect(rollProgressCopy(makeRow({ read_count: null, issue_count: null }))).toBeNull()
  })
})

describe('ThreadPool d100 pool', () => {
  it('renders every mapped face as a comic-first row', () => {
    const pool = Array.from({ length: 100 }, (_, index) =>
      makeRow({ id: index + 1, title: `Series ${index + 1}`, issue_number: String(index + 1) }),
    )

    render(
      <MemoryRouter>
        <ThreadPool
          pool={pool}
          blockedThreads={[]}
          blockingDependencyMap={{}}
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
          dieSize={100}
          onThreadClick={vi.fn()}
          onUnsnooze={vi.fn()}
          onUnskip={vi.fn()}
          onReadStale={vi.fn()}
          onToggleSnoozed={vi.fn()}
          onToggleSkipped={vi.fn()}
          onToggleStale={vi.fn()}
          onToggleBlocked={vi.fn()}
          onShuffle={vi.fn()}
          unsnoozeIsPending={false}
          unskipIsPending={false}
          shuffleIsPending={false}
        />
      </MemoryRouter>,
    )

    expect(screen.getAllByTestId('roll-pool-row')).toHaveLength(100)
    expect(screen.getByText('100 in play')).toBeInTheDocument()
    expect(screen.getByText('Series 100')).toBeInTheDocument()
  })
})
