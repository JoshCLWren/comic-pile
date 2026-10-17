import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useExcludedThreads,
  useRestoreThread,
  type QueueInvalidateFn,
  type RestoreThreadApi,
} from '../hooks/useQueue'
import { useExcludeThread } from '../hooks/useThread'
import { threadsApi as realThreadsApi } from '../services/api-threads'
import type { ThreadListItem } from '../types'

// SAFETY: each double stands in for one threadsApi method with that method's
// own argument list and resolved value, so the module double matches the real
// service surface these hooks consume.
const mockListExcluded = vi.fn<typeof realThreadsApi.listExcluded>()
const mockRestore = vi.fn<RestoreThreadApi['restore']>()
const mockExclude = vi.fn<typeof realThreadsApi.exclude>()

vi.mock('../services/api-threads', () => ({
  threadsApi: {
    listExcluded: (...args: Parameters<typeof realThreadsApi.listExcluded>) =>
      mockListExcluded(...args),
    restore: (...args: Parameters<RestoreThreadApi['restore']>) => mockRestore(...args),
    exclude: (...args: Parameters<typeof realThreadsApi.exclude>) => mockExclude(...args),
  },
}))

const invalidate = vi.fn<QueueInvalidateFn>()
const restoreApi: RestoreThreadApi = { restore: mockRestore }

function makeThread(overrides: Partial<ThreadListItem> = {}): ThreadListItem {
  return {
    id: 7,
    title: 'Descender',
    format: 'Comic',
    status: 'excluded',
    queue_position: 0,
    issues_remaining: 4,
    total_issues: 10,
    is_blocked: false,
    blocking_reasons: [],
    last_activity_at: null,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as ThreadListItem
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  // SAFETY: the endpoint returns a list envelope, so the double resolves to it.
  mockListExcluded.mockResolvedValue({
    threads: [makeThread()],
    next_page_token: null,
  } as never)
  // SAFETY: both endpoints return the affected thread record.
  mockRestore.mockResolvedValue(makeThread() as never)
  mockExclude.mockResolvedValue(makeThread() as never)
  invalidate.mockResolvedValue()
})

describe('useExcludedThreads', () => {
  it('requests exactly one bounded excluded-library page', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useExcludedThreads(true), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockListExcluded).toHaveBeenCalledTimes(1)
    expect(mockListExcluded).toHaveBeenCalledWith(undefined, 'created', null, 50)
    expect(result.current.threads.map((thread) => thread.id)).toEqual([7])
    expect(result.current.isError).toBe(false)
  })

  it('does not request the library while disabled', () => {
    const wrapper = createWrapper()
    renderHook(() => useExcludedThreads(false), { wrapper })

    expect(mockListExcluded).not.toHaveBeenCalled()
  })

  it('reports an empty shelf rather than failing when nothing is excluded', async () => {
    mockListExcluded.mockResolvedValue({ threads: [], next_page_token: null } as never)
    const wrapper = createWrapper()
    const { result } = renderHook(() => useExcludedThreads(true), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.threads).toEqual([])
    expect(result.current.isError).toBe(false)
  })

  it('surfaces a failed library read instead of pretending it is empty', async () => {
    mockListExcluded.mockRejectedValue(new Error('excluded library unavailable'))
    const wrapper = createWrapper()
    const { result } = renderHook(() => useExcludedThreads(true), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(result.current.threads).toEqual([])
  })
})

describe('useRestoreThread', () => {
  it('restores through the non-destructive endpoint and reconciles the queue', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useRestoreThread({ api: restoreApi, invalidate }), {
      wrapper,
    })

    await result.current.mutate(7)

    expect(mockRestore).toHaveBeenCalledWith(7)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(result.current.isPending).toBe(false)
  })

  it('does not reconcile the cache when the restore fails', async () => {
    mockRestore.mockRejectedValue(new Error('restore rejected'))
    const wrapper = createWrapper()
    const { result } = renderHook(() => useRestoreThread({ api: restoreApi, invalidate }), {
      wrapper,
    })

    await expect(result.current.mutate(7)).rejects.toThrow('restore rejected')

    expect(invalidate).not.toHaveBeenCalled()
    expect(result.current.isError).toBe(true)
  })
})

describe('useExcludeThread', () => {
  it('removes a series through the reversible endpoint, never the destructive one', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useExcludeThread(), { wrapper })

    await result.current.mutate(7)

    expect(mockExclude).toHaveBeenCalledWith(7)
    expect(result.current.isPending).toBe(false)
  })
})