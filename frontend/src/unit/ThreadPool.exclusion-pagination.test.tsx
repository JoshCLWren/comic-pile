import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread, ThreadExclusionReason } from '../types/rollBootstrap'

type ThreadPoolProps = Parameters<typeof ThreadPool>[0]

function blockedRows(count: number, start = 1): RollBootstrapThread[] {
  return Array.from({ length: count }, (_, index) => ({
    id: start + index,
    title: `Blocked ${start + index}`,
    format: 'Comic',
  }))
}

function inactiveRows(count: number, start = 1): ThreadExclusionReason[] {
  return Array.from({ length: count }, (_, index) => ({
    thread_id: start + index,
    title: `Out ${start + index}`,
    format: 'Comic',
    reason: index % 2 === 0 ? 'completed' : 'not_in_queue',
    detail: index % 2 === 0 ? 'Read the full series' : 'Not in the active queue',
  }))
}

function pagination(overrides: Partial<ThreadPoolProps['blockedPagination']> = {}) {
  return {
    total: 0,
    hasNextPage: false,
    isLoading: false,
    isError: false,
    onLoadMore: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
}

function renderPool(overrides: Partial<ThreadPoolProps> = {}) {
  const props: ThreadPoolProps = {
    pool: [],
    blockedThreads: [],
    blockingDependencyMap: {},
    dieSize: 6,
    isRatingView: false,
    selectedThreadId: null,
    staleThread: null,
    staleThreadCount: 0,
    snoozedThreads: [],
    snoozedExpanded: false,
    blockedExpanded: false,
    skippedThreads: [],
    skippedExpanded: false,
    staleExpanded: false,
    inactiveThreads: [],
    inactiveExpanded: false,
    onToggleInactive: vi.fn(),
    onThreadClick: vi.fn(),
    onUnsnooze: vi.fn(),
    onUnskip: vi.fn(),
    onReadStale: vi.fn(),
    onToggleSnoozed: vi.fn(),
    onToggleSkipped: vi.fn(),
    onToggleStale: vi.fn(),
    onToggleBlocked: vi.fn(),
    onShuffle: vi.fn(),
    unsnoozeIsPending: false,
    unskipIsPending: false,
    shuffleIsPending: false,
    ...overrides,
  }
  return {
    props,
    ...render(
      <MemoryRouter>
        <ThreadPool {...props} />
      </MemoryRouter>,
    ),
  }
}

describe('ThreadPool exclusion category totals and pagination (#3330)', () => {
  it('reports the blocked category total instead of the preview length and pages to the last series', () => {
    const onLoadMore = vi.fn()
    const preview = blockedRows(20)
    const everything = blockedRows(287)
    const { props, rerender } = renderPool({
      blockedExpanded: true,
      blockedThreads: preview,
      blockedPagination: pagination({ total: 287, hasNextPage: true, onLoadMore }),
    })

    // The heading is the database-truth total, not the 20-row preview.
    expect(screen.getByText('287 series waiting for earlier issues')).toBeInTheDocument()
    expect(screen.getByText('Showing 20 of 287 blocked series')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /load more/i }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    rerender(
      <MemoryRouter>
        <ThreadPool
          {...props}
          blockedThreads={everything}
          blockedPagination={pagination({ total: 287, hasNextPage: false })}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Showing 287 of 287 blocked series')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()
    // The final counted series is reachable and navigable to its thread.
    expect(screen.getByRole('link', { name: 'Blocked 287' })).toHaveAttribute(
      'href',
      '/thread/287',
    )
  })

  it('reports the out-of-pool total and keeps every row navigable with its reason', () => {
    const onLoadMore = vi.fn()
    const preview = inactiveRows(20)
    const everything = inactiveRows(23)
    const { props, rerender } = renderPool({
      inactiveExpanded: true,
      inactiveThreads: preview,
      inactivePagination: pagination({ total: 23, hasNextPage: true, onLoadMore }),
    })

    expect(screen.getByText('23 series out of the roll pool')).toBeInTheDocument()
    expect(screen.getByText('Showing 20 of 23 out-of-pool series')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /load more/i }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    rerender(
      <MemoryRouter>
        <ThreadPool
          {...props}
          inactiveThreads={everything}
          inactivePagination={pagination({ total: 23, hasNextPage: false })}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Showing 23 of 23 out-of-pool series')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Out 23' })).toHaveAttribute('href', '/thread/23')
    expect(screen.getAllByText('Not in the active queue').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Read the full series').length).toBeGreaterThan(0)
  })

  it('shows a complete "N of N" footer when a category fits in one page', () => {
    renderPool({
      blockedExpanded: true,
      blockedThreads: blockedRows(3),
      blockedPagination: pagination({ total: 3 }),
      inactiveExpanded: true,
      inactiveThreads: inactiveRows(3),
      inactivePagination: pagination({ total: 3 }),
    })

    expect(screen.getByText('3 series waiting for earlier issues')).toBeInTheDocument()
    expect(screen.getByText('Showing 3 of 3 blocked series')).toBeInTheDocument()
    expect(screen.getByText('Showing 3 of 3 out-of-pool series')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()
  })

  it('renders loading, error, and retry states for an expanded category', () => {
    const onRetry = vi.fn()
    const { props, rerender } = renderPool({
      blockedExpanded: true,
      blockedPagination: pagination({ total: 25, hasNextPage: true, isLoading: true }),
    })

    expect(screen.getByText('Loading blocked series…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()

    rerender(
      <MemoryRouter>
        <ThreadPool
          {...props}
          blockedThreads={blockedRows(20)}
          blockedPagination={pagination({ total: 25, hasNextPage: true, isError: true, onRetry })}
        />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    // Already-loaded rows stay visible while the retry is offered.
    expect(screen.getByText('Blocked 20')).toBeInTheDocument()
  })

  it('keeps the empty state when both categories are truly empty', () => {
    renderPool({
      blockedPagination: pagination({ total: 0 }),
      inactivePagination: pagination({ total: 0 }),
    })

    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    expect(screen.queryByText(/series waiting for earlier issues/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/series out of the roll pool/i)).not.toBeInTheDocument()
  })

  it('explains a blocked series with its dependency detail when expanded', () => {
    renderPool({
      blockedExpanded: true,
      blockedThreads: [
        {
          id: 9,
          title: 'Waiting Series',
          format: 'Comic',
          blocking_reasons: ['Blocked by Saga: #1'],
        },
      ],
      blockingDependencyMap: {
        9: [{ thread_id: 4, thread_title: 'Saga', issue_number: '1', label: 'Blocked by Saga: #1' }],
      },
      blockedPagination: pagination({ total: 1 }),
    })

    expect(screen.getByText('Blocked by Saga: #1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open Saga/i })).toHaveAttribute(
      'href',
      '/thread/4',
    )
  })
})
