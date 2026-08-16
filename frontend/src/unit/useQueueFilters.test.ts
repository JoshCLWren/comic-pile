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

it('sorts alphabetically and by created date', () => {
     const oldest = makeThread({ id: 1, title: 'Zeta', queue_position: 2, created_at: '2024-01-01' })
     const newest = makeThread({ id: 2, title: 'Alpha', queue_position: 1, created_at: '2025-01-01' })

     const { result: alphabetical } = renderHook(() =>
       useQueueFilters([oldest, newest], 'alphabetical'),
     )
    expect(alphabetical.current.sortedThreads.map((t) => t.title)).toEqual(['Alpha', 'Zeta'])

    const { result: created } = renderHook(() =>
      useQueueFilters([oldest, newest], 'created'),
    )
    expect(created.current.sortedThreads.map((t) => t.id)).toEqual([2, 1])
  })

it('returns all active threads sorted by position since search is handled on backend', () => {
     const threads = [
       makeThread({ id: 1, title: 'Saga', queue_position: 1 }),
       makeThread({ id: 2, title: 'Descender', queue_position: 2 }),
     ]
     const { result } = renderHook(() => useQueueFilters(threads, 'position'))
     expect(result.current.filteredThreads.map((t) => t.id)).toEqual([1, 2])
   })

it('returns all active threads when no search filter applied', () => {
     const threads = [
       makeThread({ id: 1, title: 'Saga', queue_position: 1 }),
       makeThread({ id: 2, title: 'Descender', queue_position: 2 }),
     ]
     const { result } = renderHook(() => useQueueFilters(threads, 'position'))
     expect(result.current.filteredThreads.length).toBe(2)
   })
})
