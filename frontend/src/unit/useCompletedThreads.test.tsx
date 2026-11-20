import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCompletedThreads, COMPLETED_PAGE_SIZE } from '../hooks/useCompletedThreads'
import { threadsApi as realThreadsApi } from '../services/api-threads'

const listCompleted = vi.fn<typeof realThreadsApi.listCompleted>()
const api: Pick<typeof realThreadsApi, 'listCompleted'> = { listCompleted }

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
  listCompleted.mockResolvedValue({ threads: [], next_page_token: null, active_count: 0 })
})

describe('useCompletedThreads: finished series are independent of active Queue (#5171)', () => {
  it('fetches only one bounded Rust completed page on first render', async () => {
    const { result } = renderHook(() => useCompletedThreads(true, api), {
      wrapper: createWrapper(),
    })
    await waitFor(() => expect(listCompleted).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.threads).toEqual([]))
    expect(listCompleted).toHaveBeenCalledWith(
      undefined, 'created', undefined, COMPLETED_PAGE_SIZE,
    )
    expect(result.current.hasNextPage).toBe(false)
  })

  it('exposes the first-page loading state before the bounded page lands', async () => {
    const { result } = renderHook(() => useCompletedThreads(true, api), {
      wrapper: createWrapper(),
    })

    // While the dedicated collection is in flight the shelf must read as
    // loading, not as settled-empty (the original #5171 disappearance).
    await waitFor(() => expect(result.current.isLoading).toBe(true))
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.threads).toEqual([])
  })

  it('retries the failed continuation cursor rather than restarting at page one', async () => {
    listCompleted
      .mockResolvedValueOnce({
        threads: [
          // SAFETY: the hook reads only id and status from this abbreviated page fixture.
          { id: 1, title: 'Finished A', status: 'completed' } as never,
        ],
        next_page_token: 'page-two',
        active_count: 0,
      })
      .mockRejectedValueOnce(new Error('page two temporarily unavailable'))
      .mockResolvedValueOnce({
        threads: [
          // SAFETY: the hook reads only id and status from this abbreviated page fixture.
          { id: 2, title: 'Finished B', status: 'completed' } as never,
        ],
        next_page_token: null,
        active_count: 0,
      })

    const { result } = renderHook(() => useCompletedThreads(true, api), {
      wrapper: createWrapper(),
    })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))

    await act(async () => { await result.current.loadMore() })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.threads.map((item) => item.id)).toEqual([1])

    await act(async () => { await result.current.retry() })
    await waitFor(() => expect(result.current.threads.map((item) => item.id)).toEqual([1, 2]))
    expect(listCompleted).toHaveBeenNthCalledWith(
      2, undefined, 'created', 'page-two', COMPLETED_PAGE_SIZE,
    )
    expect(listCompleted).toHaveBeenNthCalledWith(
      3, undefined, 'created', 'page-two', COMPLETED_PAGE_SIZE,
    )
  })

  it('separately paginates finished rows and leaves active rows out', async () => {
    listCompleted
      .mockResolvedValueOnce({
        threads: [
          // SAFETY: this fixture stubs only list attributes the hook reads (id and status).
          { id: 1, title: 'Finished A', status: 'completed' } as never,
          // SAFETY: this fixture stubs only list attributes the hook reads (id and status).
          { id: 2, title: 'Finished B', status: 'completed' } as never,
        ],
        next_page_token: 'finished-next-page',
        active_count: 0,
      })
      .mockResolvedValueOnce({
        threads: [
          // SAFETY: this fixture stubs only list attributes the hook reads (id and status).
          { id: 2, title: 'Finished B', status: 'completed' } as never,
          // SAFETY: this fixture stubs only list attributes the hook reads (id and status).
          { id: 3, title: 'Finished C', status: 'completed' } as never,
        ],
        next_page_token: null,
        active_count: 0,
      })

    const { result } = renderHook(() => useCompletedThreads(true, api), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.threads.map((item) => item.id)).toEqual([1, 2]))
    expect(result.current.hasNextPage).toBe(true)
    expect(listCompleted).toHaveBeenCalledTimes(1)

    await act(async () => { await result.current.loadMore() })
    await waitFor(() =>
      expect(result.current.threads.map((item) => item.id)).toEqual([1, 2, 3]),
    )
    expect(listCompleted).toHaveBeenNthCalledWith(
      2, undefined, 'created', 'finished-next-page', COMPLETED_PAGE_SIZE,
    )
    expect(result.current.hasNextPage).toBe(false)

    await act(async () => { await result.current.loadMore() })
    expect(listCompleted).toHaveBeenCalledTimes(2)
  })

  it('never calls the API while disabled', async () => {
    const { result } = renderHook(() => useCompletedThreads(false, api), {
      wrapper: createWrapper(),
    })
    expect(result.current.threads).toEqual([])
    expect(listCompleted).not.toHaveBeenCalled()
  })
})
