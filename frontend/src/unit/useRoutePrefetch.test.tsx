import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { queueThreadsQueryOptions, QUEUE_PAGE_SIZE } from '../hooks/useQueue'
import { queryKeys } from '../query/queryKeys'
import type { RoutePrefetchDependencies } from '../query/routePrefetch'

type LoaderResult = { default: () => null }

const routeLoaderKeys = [
  'roll',
  'queue',
  'threadDetail',
  'history',
  'session',
  'crossovers',
  'glossary',
  'whatsNew',
  'login',
  'register',
] as const

const routeLoaders: Record<string, Mock<() => Promise<LoaderResult>>> = {}
for (const key of routeLoaderKeys) {
  routeLoaders[key] = vi.fn(() => Promise.resolve({ default: () => null }))
}

const prefetchInfiniteQuery = vi.fn(() => Promise.resolve(undefined))

const deps: RoutePrefetchDependencies = {
  routeModules: routeLoaders,
  queryClient: { prefetchInfiniteQuery },
}

import { useRoutePrefetch } from '../hooks/useRoutePrefetch'
import { resetRoutePrefetchState } from '../query/routePrefetch'

const FALLBACK_DELAY_MS = 800

function flushIdleWork(): void {
  act(() => vi.advanceTimersByTime(FALLBACK_DELAY_MS + 1))
}

function wrapper(initialEntry = '/') {
  return function RoutePrefetchWrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('requestIdleCallback', undefined)
  vi.stubGlobal('cancelIdleCallback', undefined)
  resetRoutePrefetchState()
  for (const key of routeLoaderKeys) routeLoaders[key].mockClear()
  prefetchInfiniteQuery.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useRoutePrefetch', () => {
  it('schedules the likely next chunk for the current authenticated screen', () => {
    renderHook(() => useRoutePrefetch(true, deps), { wrapper: wrapper('/') })
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).not.toHaveBeenCalled()
  })

  it('does nothing for non-retained routes', () => {
    // Using a non-retained route such as '/crossovers' with prefetch enabled
    renderHook(() => useRoutePrefetch(true, deps), { wrapper: wrapper('/crossovers') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
  })

  it('does nothing when prefetching is disabled', () => {
    renderHook(() => useRoutePrefetch(false, deps), { wrapper: wrapper('/') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('cancels pending work when the screen unmounts before idle flush', () => {
    const { unmount } = renderHook(() => useRoutePrefetch(true, deps), {
      wrapper: wrapper('/'),
    })
    unmount()
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('deduplicates across route changes while the screen is mounted', () => {
    const { rerender } = renderHook(({ enabled }) => useRoutePrefetch(enabled, deps), {
      initialProps: { enabled: true },
      wrapper: wrapper('/queue'),
    })
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)

    rerender({ enabled: true })
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
  })

  it('warms the canonical bounded queue first page from the Roll screen', () => {
    renderHook(() => useRoutePrefetch(true, deps), { wrapper: wrapper('/') })
    flushIdleWork()

    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)
    expect(prefetchInfiniteQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: queueThreadsQueryOptions().queryKey,
        queryFn: expect.any(Function),
        initialPageParam: null,
        getNextPageParam: expect.any(Function),
      }),
    )
    // The warmed key must be exactly the key the Queue screen consumes.
    expect(queueThreadsQueryOptions().queryKey).toEqual(
      queryKeys.queue.list({ search: undefined, sort: 'position', pageSize: QUEUE_PAGE_SIZE }),
    )
  })

  it('warms the bounded queue first page from a thread detail path', () => {
    renderHook(() => useRoutePrefetch(true, deps), { wrapper: wrapper('/thread/123') })
    flushIdleWork()

    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)
    expect(prefetchInfiniteQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: queueThreadsQueryOptions().queryKey,
        queryFn: expect.any(Function),
        initialPageParam: null,
        getNextPageParam: expect.any(Function),
      }),
    )
  })

  it('does not warm data from screens whose reads bypass the query cache', () => {
    for (const path of ['/queue', '/history', '/sessions/456']) {
      renderHook(() => useRoutePrefetch(true, deps), { wrapper: wrapper(path) })
      flushIdleWork()
    }

    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('deduplicates data warming across route changes while the screen is mounted', () => {
    const { rerender } = renderHook(({ enabled }) => useRoutePrefetch(enabled, deps), {
      initialProps: { enabled: true },
      wrapper: wrapper('/'),
    })
    flushIdleWork()

    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)

    rerender({ enabled: true })
    flushIdleWork()

    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)
  })
})