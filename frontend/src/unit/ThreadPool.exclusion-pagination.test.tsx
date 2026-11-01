import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { RollBootstrapThread, ThreadExclusionReason } from '../types/rollBootstrap'

type PoolProps = Parameters<typeof ThreadPool>[0]

function mount(overrides: Partial<PoolProps> = {}) {
  const onThreadClick = vi.fn()
  const onToggleBlocked = vi.fn()
  const onToggleInactive = vi.fn()
  const props: PoolProps = {
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
    onToggleInactive,
    onThreadClick,
    onUnsnooze: vi.fn(),
    onUnskip: vi.fn(),
    onReadStale: vi.fn(),
    onToggleSnoozed: vi.fn(),
    onToggleSkipped: vi.fn(),
    onToggleStale: vi.fn(),
    onToggleBlocked,
    onShuffle: vi.fn(),
    unsnoozeIsPending: false,
    unskipIsPending: false,
    shuffleIsPending: false,
    ...overrides,
  }
  render(<MemoryRouter><ThreadPool {...props} /></MemoryRouter>)
  return { onThreadClick, onToggleBlocked, onToggleInactive }
}

const blocked: RollBootstrapThread = {
  id: 3, title: 'Locked By Earlier Issue', format: 'Comic',
  blocking_reasons: ['Read Saga #5 first'],
}
const inactive: ThreadExclusionReason = {
  thread_id: 11, title: 'Completed Vol. 2', format: 'Comic',
  reason: 'completed', detail: 'Read the full series',
}

describe('Roll diagnostics removal (#4441)', () => {
  it('does not show blocked, stale or out-of-pool panels even with legacy counts', () => {
    const controls = mount({
      pool: [{ id: 8, title: 'Saga', format: 'Comic', issue_number: '2' }],
      blockedThreads: [blocked],
      blockedExpanded: true,
      blockedPagination: {
        total: 287, hasNextPage: true, isError: true, isLoading: false,
        onLoadMore: vi.fn(), onRetry: vi.fn(),
      },
      staleThread: { id: 9, title: 'Old Series', format: 'Comic', days: 42 },
      staleThreadCount: 90,
      staleExpanded: true,
      inactiveThreads: [inactive],
      inactiveExpanded: true,
      inactivePagination: {
        total: 604, hasNextPage: true, isError: false, isLoading: true,
        onLoadMore: vi.fn(), onRetry: vi.fn(),
      },
    })
    expect(screen.getByRole('button', { name: /Die face 1: Saga/i })).toBeInTheDocument()
    for (const text of [
      /series waiting for earlier issues/i,
      /series you haven't opened recently/i,
      /series out of the roll pool/i,
      /Locked By Earlier Issue/i,
      /Completed Vol. 2/i,
      /Old Series/i,
      /Load more/i,
    ]) expect(screen.queryByText(text)).not.toBeInTheDocument()
    expect(controls.onToggleBlocked).not.toHaveBeenCalled()
    expect(controls.onToggleInactive).not.toHaveBeenCalled()
  })

  it('treats a zero eligible pool as empty even if legacy exclusion counts remain', () => {
    mount({ blockedThreads: [blocked], inactiveThreads: [inactive], blockedExpanded: true })
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add a Series/i })).toBeInTheDocument()
  })

  it('continues to surface snoozed options without retired report panels', () => {
    mount({ snoozedThreads: [{ id: 12, title: 'On break', format: 'Comic' }], snoozedExpanded: true })
    expect(screen.getByText('On break')).toBeInTheDocument()
    expect(screen.getByText('Snoozed (1)')).toBeInTheDocument()
    expect(screen.queryByText(/out of the roll pool/i)).not.toBeInTheDocument()
  })
})
