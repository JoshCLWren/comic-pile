import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useInfiniteCollection, collectAllPages } from '../pagination'

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('collectAllPages', () => {
  it('collects all pages until exhausted', async () => {
    const pages = [
      { data: ['a', 'b'], next: 'token1' },
      { data: ['c', 'd'], next: 'token2' },
      { data: ['e'], next: null },
    ]
    let callCount = 0
    const fetchPage = vi.fn((_token: string | null) => {
      const page = pages[callCount++]
      return Promise.resolve(page)
    })

    const result = await collectAllPages({
      fetchPage,
      selectItems: (p: { data: string[]; next: string | null }) => p.data,
      selectNextToken: (p: { data: string[]; next: string | null }) => p.next,
    })

    expect(result.items).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(result.pages).toEqual(pages)
    expect(result.pageCount).toBe(3)
    expect(result.stopReason).toBe('exhausted')
    expect(fetchPage).toHaveBeenCalledTimes(3)
  })

  it('stops at maxPages', async () => {
    const pages = [
      { data: ['a'], next: '1' },
      { data: ['b'], next: '2' },
      { data: ['c'], next: '3' },
    ]
    let callCount = 0
    const fetchPage = vi.fn((_token: string | null) => {
      const page = pages[callCount++]
      return Promise.resolve(page)
    })

    const result = await collectAllPages({
      fetchPage,
      selectItems: (p: { data: string[]; next: string }) => p.data,
      selectNextToken: (p: { data: string[]; next: string }) => p.next,
      maxPages: 2,
    })

    expect(result.items).toEqual(['a', 'b'])
    expect(result.pageCount).toBe(2)
    expect(result.stopReason).toBe('max-pages')
  })

  it('detects repeated tokens', async () => {
    const pages = [
      { data: ['a'], next: 'token1' },
      { data: ['b'], next: 'token1' },
    ]
    let callCount = 0
    const fetchPage = vi.fn((_token: string | null) => {
      const page = pages[callCount++]
      return Promise.resolve(page)
    })

    const result = await collectAllPages({
      fetchPage,
      selectItems: (p: { data: string[]; next: string }) => p.data,
      selectNextToken: (p: { data: string[]; next: string }) => p.next,
    })

    expect(result.stopReason).toBe('repeat-token')
    expect(result.pageCount).toBe(2)
  })

  it('throws on invalid maxPages', async () => {
    await expect(collectAllPages({
      fetchPage: async () => ({}),
      selectItems: () => [],
      selectNextToken: () => null,
      maxPages: 0,
    })).rejects.toThrow(RangeError)
  })
})

describe('useInfiniteCollection', () => {
  it('initializes and fetches first page', async () => {
    const mockPage = { items: [1, 2], nextToken: 't1' }
    const queryFn = vi.fn().mockResolvedValue(mockPage)

    const { result } = renderHook(
      () => useInfiniteCollection({
        queryKey: ['test'],
        queryFn,
        initialPageParam: null,
        getNextPageParam: (p: { items: number[]; nextToken: string }) => p.nextToken,
        selectPage: (p: { items: number[]; nextToken: string }) => p.items,
      }),
      { wrapper: createWrapper() }
    )

    expect(result.current.isInitialLoading).toBe(true)

    await waitFor(() => expect(result.current.isInitialLoading).toBe(false))

    expect(result.current.items).toEqual([1, 2])
    expect(result.current.hasNextPage).toBe(true)
    expect(result.current.nextPageToken).toBe('t1')
  })

  it('deduplicates items using selectId', async () => {
    const pages = [
      { items: [{ id: 1, v: 'a' }, { id: 2, v: 'b' }], next: 't1' },
      { items: [{ id: 2, v: 'b' }, { id: 3, v: 'c' }], next: null },
    ]
    let callCount = 0
    const queryFn = vi.fn(() => Promise.resolve(pages[callCount++]))

    const { result } = renderHook(
      () => useInfiniteCollection({
        queryKey: ['test'],
        queryFn,
        initialPageParam: null,
        getNextPageParam: (p: { items: { id: number; v: string }[]; next: string | null }) => p.next,
        selectPage: (p: { items: { id: number; v: string }[]; next: string | null }) => p.items,
        selectId: (item: { id: number; v: string }) => item.id,
      }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => expect(result.current.isInitialLoading).toBe(false))
    
    // Fetch next page
    await result.current.fetchNextPage()
    await waitFor(() => expect(result.current.isNextPageLoading).toBe(false))

    expect(result.current.items).toHaveLength(3)
    expect(result.current.items.map(i => i.id)).toEqual([1, 2, 3])
  })

  it('handles errors', async () => {
    const queryFn = vi.fn().mockRejectedValue(new Error('Fetch failed'))

    const { result } = renderHook(
      () => useInfiniteCollection({
        queryKey: ['test'],
        queryFn,
        initialPageParam: null,
        getNextPageParam: (_p: { items: never[] }) => null,
        selectPage: (_p: { items: never[] }) => [],
        retry: false,
      }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(Error)
  })

  it('handles disabled state', () => {
    const queryFn = vi.fn()
    const { result } = renderHook(
      () => useInfiniteCollection({
        queryKey: ['test'],
        queryFn,
        initialPageParam: null,
        getNextPageParam: (_p: { items: never[] }) => null,
        selectPage: (_p: { items: never[] }) => [],
        enabled: false,
      }),
      { wrapper: createWrapper() }
    )

    expect(result.current.isLoading).toBe(false)
    expect(queryFn).not.toHaveBeenCalled()
  })
})
