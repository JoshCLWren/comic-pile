import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueCompletedSearch } from '../pages/QueuePage/useQueueCompletedSearch'

interface MatchableThread {
  id: number
  title: string
}

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  showToast: vi.fn(),
  completedThreads: [] as MatchableThread[] | undefined,
  excludedThreads: [] as MatchableThread[] | undefined,
  list: vi.fn(),
  bulkMarkUnread: vi.fn(),
}))

vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate }))
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ showToast: mocks.showToast }) }))
vi.mock('../hooks/useCompletedThreads', () => ({
  useCompletedThreads: () => ({ threads: mocks.completedThreads }),
}))
vi.mock('../hooks/useQueue', () => ({
  useExcludedThreads: () => ({ threads: mocks.excludedThreads }),
}))
vi.mock('../services/api-issues', () => ({
  issuesApi: { list: mocks.list, bulkMarkUnread: mocks.bulkMarkUnread },
}))

describe('useQueueCompletedSearch', () => {
  beforeEach(() => {
    mocks.navigate.mockReset()
    mocks.showToast.mockReset()
    mocks.list.mockReset()
    mocks.bulkMarkUnread.mockReset()
    mocks.completedThreads = []
    mocks.excludedThreads = []
  })

  it('does not search completed or excluded shelves for an empty query', () => {
    mocks.completedThreads = [{ id: 1, title: 'Daredevil' }]
    mocks.excludedThreads = [{ id: 2, title: 'Daredevil Annual' }]
    const { result } = renderHook(() => useQueueCompletedSearch('   '))

    expect(result.current.isSearching).toBe(false)
    expect(result.current.completedMatches).toEqual([])
    expect(result.current.excludedMatches).toEqual([])
  })

  it('treats missing shelf data as an empty match set', () => {
    mocks.completedThreads = undefined
    mocks.excludedThreads = undefined
    const { result } = renderHook(() => useQueueCompletedSearch('anything'))

    expect(result.current.completedMatches).toEqual([])
    expect(result.current.excludedMatches).toEqual([])
  })

  it('filters completed and excluded series case-insensitively and opens each', async () => {
    mocks.completedThreads = [
      { id: 5, title: 'Daredevil' },
      { id: 6, title: 'Batman' },
    ]
    mocks.excludedThreads = [
      { id: 7, title: 'Daredevil Annual' },
      { id: 8, title: 'Superman' },
    ]
    const { result } = renderHook(() => useQueueCompletedSearch('  DaReDeViL '))

    await waitFor(() => expect(result.current.isSearching).toBe(true))
    expect(result.current.completedMatches).toEqual([
      { id: 5, title: 'Daredevil', status: 'completed' },
    ])
    expect(result.current.excludedMatches).toEqual([
      { id: 7, title: 'Daredevil Annual', status: 'excluded' },
    ])

    act(() => result.current.openCompletedSeries(5))
    act(() => result.current.openExcludedSeries(7))
    expect(mocks.navigate).toHaveBeenNthCalledWith(1, '/thread/5')
    expect(mocks.navigate).toHaveBeenNthCalledWith(2, '/thread/7')
  })

  it('restores every read issue across pages before invalidating the queue', async () => {
    mocks.list
      .mockResolvedValueOnce({ issues: [{ id: 11 }, { id: 12 }], next_page_token: 'page-2' })
      .mockResolvedValueOnce({ issues: [{ id: 13 }], next_page_token: null })
    mocks.bulkMarkUnread.mockResolvedValueOnce({ id: 3 })
    const { result } = renderHook(() => useQueueCompletedSearch('anything'))

    await act(async () => { await result.current.handleRestoreCompletedSeries(42) })

    expect(mocks.list).toHaveBeenNthCalledWith(1, 42, {
      status: 'read', page_size: 100, page_token: undefined,
    })
    expect(mocks.list).toHaveBeenNthCalledWith(2, 42, {
      status: 'read', page_size: 100, page_token: 'page-2',
    })
    expect(mocks.bulkMarkUnread).toHaveBeenCalledWith([11, 12, 13])
    expect(mocks.showToast).toHaveBeenCalledWith('Restored series issues to unread', 'success')
  })

  it('reports an empty restore without issuing a write', async () => {
    mocks.list.mockResolvedValueOnce({ issues: [], next_page_token: null })
    const { result } = renderHook(() => useQueueCompletedSearch('anything'))

    await act(async () => { await result.current.handleRestoreCompletedSeries(42) })

    expect(mocks.showToast).toHaveBeenCalledWith('No read issues to restore', 'info')
    expect(mocks.bulkMarkUnread).not.toHaveBeenCalled()
  })

  it('reports a restore failure without hiding the underlying detail', async () => {
    mocks.list.mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useQueueCompletedSearch('anything'))

    await act(async () => { await result.current.handleRestoreCompletedSeries(42) })

    expect(mocks.showToast).toHaveBeenCalledWith('Failed to restore unread: boom', 'error')
    expect(mocks.bulkMarkUnread).not.toHaveBeenCalled()
  })
})
