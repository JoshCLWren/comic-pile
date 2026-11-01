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

describe('Retired Roll exclusion details (#4441)', () => {
  it('never leaks excluded thread titles, dependency details or navigable links', () => {
    mount({
      blockedThreads: [blocked],
      blockingDependencyMap: {
        3: [{ thread_id: 4, thread_title: 'Saga', issue_number: '5', label: 'Read Saga #5 first' }],
      },
      inactiveThreads: [inactive],
      blockedExpanded: true, inactiveExpanded: true,
    })
    expect(screen.queryByText('Locked By Earlier Issue')).not.toBeInTheDocument()
    expect(screen.queryByText('Read Saga #5 first')).not.toBeInTheDocument()
    expect(screen.queryByText('Completed Vol. 2')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Saga/i })).not.toBeInTheDocument()
  })

  it('preserves direct actions on real eligible die faces', () => {
    const comic = { id: 24, title: 'Planetary', format: 'Comic', issue_number: '7' }
    const { onThreadClick } = mount({
      pool: [comic],
      blockedThreads: [blocked],
      blockedExpanded: true,
    })
    fireEvent.click(screen.getByRole('button', { name: /Die face 1: Planetary/i }))
    expect(onThreadClick).toHaveBeenCalledWith(comic)
    expect(screen.queryByText('Locked By Earlier Issue')).not.toBeInTheDocument()
  })

  it('offers queue navigation for snoozed-only state without an exclusion report', () => {
    mount({
      snoozedThreads: [{ id: 2, title: 'Paused', format: 'Comic' }],
      inactiveThreads: [inactive],
    })
    expect(screen.getByText('Every series is snoozed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to Queue' })).toBeInTheDocument()
    expect(screen.queryByText('Completed Vol. 2')).not.toBeInTheDocument()
  })

  it('retains keyboard access to eligible issue selection', () => {
    const comic = { id: 24, title: 'Planetary', format: 'Comic' }
    const { onThreadClick } = mount({ pool: [comic], inactiveThreads: [inactive] })
    const face = screen.getByRole('button', { name: /Die face 1: Planetary/i })
    fireEvent.keyDown(face, { key: 'Enter' })
    expect(onThreadClick).toHaveBeenCalledWith(comic)
  })
})
