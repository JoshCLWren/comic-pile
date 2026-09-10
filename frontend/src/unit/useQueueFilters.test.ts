import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useQueueFilters } from '../pages/QueuePage/useQueueFilters'
import type { Thread } from '../types'

function makeThread(overrides: Partial<Thread>): Thread {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    status: 'active',
    queue_position: 1,
    issues_remaining: 1,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('useQueueFilters', () => {
  it('partitions active and completed threads and defaults to position sort', () => {
    const active1 = makeThread({ id: 1, title: 'Alpha', queue_position: 2 })
    const active2 = makeThread({ id: 2, title: 'Beta', queue_position: 1 })
    const completed = makeThread({
      id: 3,
      title: 'Done',
      status: 'completed',
      queue_position: 0,
    })

    const { result } = renderHook(() =>
      useQueueFilters([active1, active2, completed], 'position'),
    )

    expect(result.current.activeThreads.map((t) => t.id)).toEqual([2, 1])
    expect(result.current.completedThreads.map((t) => t.id)).toEqual([3])
    expect(result.current.sortedThreads.map((t) => t.id)).toEqual([2, 1])
    expect(result.current.filteredThreads.map((t) => t.id)).toEqual([2, 1])
  })

  it('returns empty arrays when the page query has no threads yet', () => {
    const { result } = renderHook(() => useQueueFilters(undefined, 'position'))
    expect(result.current.activeThreads).toEqual([])
    expect(result.current.completedThreads).toEqual([])
    expect(result.current.filteredThreads).toEqual([])
  })

  it('preserves server cursor order for alphabetical and created sorts', () => {
    // Server keyset pages arrive in SQL ORDER BY order; the client must not
    // re-sort with localeCompare/date parsing, which would interleave later
    // pages into earlier ones (issue #2452).
    const oldest = makeThread({ id: 1, title: 'Zeta', queue_position: 2, created_at: '2024-01-01' })
    const newest = makeThread({ id: 2, title: 'Alpha', queue_position: 1, created_at: '2025-01-01' })

    const { result: alphabetical } = renderHook(() =>
      useQueueFilters([oldest, newest], 'alphabetical'),
    )
    expect(alphabetical.current.sortedThreads.map((t) => t.title)).toEqual(['Zeta', 'Alpha'])

    const { result: created } = renderHook(() =>
      useQueueFilters([oldest, newest], 'created'),
    )
    expect(created.current.sortedThreads.map((t) => t.id)).toEqual([1, 2])
  })

  it('returns all active threads sorted by position since search is handled on backend', () => {
    const threads = [
      makeThread({ id: 1, title: 'Saga', queue_position: 1 }),
      makeThread({ id: 2, title: 'Descender', queue_position: 2 }),
    ]
    const { result } = renderHook(() => useQueueFilters(threads, 'position'))
    expect(result.current.filteredThreads.map((t) => t.id)).toEqual([1, 2])
  })

  it('sorts position with feasible-only ordering (unblocked before blocked)', () => {
    const blockedFirst = makeThread({ id: 1, title: 'Blocked', queue_position: 1, is_blocked: true })
    const unblockedSecond = makeThread({ id: 2, title: 'Readable', queue_position: 2, is_blocked: false })
    const blockedThird = makeThread({ id: 3, title: 'Blocked Later', queue_position: 3, is_blocked: true })
    const unblockedFourth = makeThread({ id: 4, title: 'Readable Later', queue_position: 4, is_blocked: false })

    const { result } = renderHook(() =>
      useQueueFilters([blockedFirst, unblockedSecond, blockedThird, unblockedFourth], 'position'),
    )
    expect(result.current.sortedThreads.map((t) => t.id)).toEqual([2, 4, 1, 3])
  })

  it('returns all active threads when no search filter applied', () => {
    const threads = [
      makeThread({ id: 1, title: 'Saga', queue_position: 1 }),
      makeThread({ id: 2, title: 'Descender', queue_position: 2 }),
    ]
    const { result } = renderHook(() => useQueueFilters(threads, 'position'))
    expect(result.current.filteredThreads.length).toBe(2)
  })

  it('flattens multi-page Title order without re-sorting or interleaving loaded rows', () => {
    // Regression for issue #2452: the server returns deterministic keyset
    // pages in SQL title order. Concatenating pages must preserve that exact
    // order — no localeCompare reshuffle, no row interleaving, no dupes.
    const page1 = [
      makeThread({ id: 1, title: 'Batman', queue_position: 5 }),
      makeThread({ id: 2, title: 'Descender', queue_position: 1 }),
      makeThread({ id: 3, title: 'Saga', queue_position: 3 }),
    ]
    const page2 = [
      makeThread({ id: 4, title: 'Watchmen', queue_position: 4 }),
      makeThread({ id: 5, title: 'Y: The Last Man', queue_position: 2 }),
    ]
    const page3 = [
      makeThread({ id: 6, title: 'Zot!', queue_position: 6 }),
    ]

    const { result } = renderHook(() =>
      useQueueFilters([...page1, ...page2, ...page3], 'alphabetical'),
    )

    expect(result.current.activeThreads.map((t) => t.id)).toEqual([1, 2, 3, 4, 5, 6])
    expect(result.current.sortedThreads.map((t) => t.id)).toEqual([1, 2, 3, 4, 5, 6])
    expect(result.current.filteredThreads.map((t) => t.id)).toEqual([1, 2, 3, 4, 5, 6])
    expect(result.current.filteredThreads.map((t) => t.title)).toEqual([
      'Batman',
      'Descender',
      'Saga',
      'Watchmen',
      'Y: The Last Man',
      'Zot!',
    ])
  })

  it('flattens multi-page Created order without client re-sort', () => {
    const page1 = [
      makeThread({ id: 1, title: 'Newest', created_at: '2025-06-01T00:00:00Z' }),
      makeThread({ id: 2, title: 'Middle', created_at: '2025-03-01T00:00:00Z' }),
    ]
    const page2 = [
      makeThread({ id: 3, title: 'Older', created_at: '2025-01-01T00:00:00Z' }),
      makeThread({ id: 4, title: 'Oldest', created_at: '2024-06-01T00:00:00Z' }),
    ]

    const { result } = renderHook(() => useQueueFilters([...page1, ...page2], 'created'))

    expect(result.current.filteredThreads.map((t) => t.id)).toEqual([1, 2, 3, 4])
    expect(result.current.filteredThreads.map((t) => t.title)).toEqual([
      'Newest',
      'Middle',
      'Older',
      'Oldest',
    ])
  })
})
