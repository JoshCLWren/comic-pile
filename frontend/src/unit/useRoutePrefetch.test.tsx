import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { queryKeys, type QueueSort } from '../query/queryKeys'
import { QUEUE_PAGE_SIZE } from '../hooks/useQueue'

const { routeLoaderKeys, routeLoaders } = vi.hoisted(() => {
  const routeLoaderKeys = [
    'roll',
    'queue',
    'threadDetail',
    'history',
    'session',
    'crossovers',
    'help',
    'whatsNew',
    'login',
    'register',
  ] as const

  const loaders: Record<string, Mock> = {}
  for (const key of routeLoaderKeys) {
    loaders[key] = vi.fn(() => Promise.resolve({ default: () => null }))
  }
  return { routeLoaderKeys, routeLoaders: loaders }
})

vi.mock('../routes/routeModules', () => ({
  routeModules: routeLoaders,
  lazyRoute: vi.fn(),
}))

const mockPrefetchQuery = vi.hoisted(() => {
  return vi.fn()
})

vi.mock('../query/queryClient', () => ({
  queryClient: {
    prefetchQuery: mockPrefetchQuery,
  },
}))

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
  mockPrefetchQuery.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useRoutePrefetch', () => {
  it('schedules the likely next chunk for the current authenticated screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/') })
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).not.toHaveBeenCalled()
  })

  it('does nothing for non-retained routes', () => {
    // Using a non-retained route such as '/crossovers' with prefetch enabled
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/crossovers') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
  })

  it('does nothing when prefetching is disabled', () => {
    renderHook(() => useRoutePrefetch(false), { wrapper: wrapper('/') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
  })

  it('cancels pending work when the screen unmounts before idle flush', () => {
    const { unmount } = renderHook(() => useRoutePrefetch(true), {
      wrapper: wrapper('/'),
    })
    unmount()
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
    expect(mockPrefetchQuery).not.toHaveBeenCalled()
  })

  it('deduplicates across route changes while the screen is mounted', () => {
    const { rerender } = renderHook(({ enabled }) => useRoutePrefetch(enabled), {
      initialProps: { enabled: true },
      wrapper: wrapper('/queue'),
    })
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
  })

  // Data prefetching tests
  it('prefetches bootstrap data for Roll screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/') })
    flushIdleWork()

    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.roll.bootstrap(),
      { staleTime: 1000, retry: false }
    )
  })

  it('prefetches queue list data for Queue screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/queue') })
    flushIdleWork()

    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.queue.list({ search: undefined, sort: 'position' as QueueSort, pageSize: QUEUE_PAGE_SIZE }),
      { staleTime: 1000, retry: false }
    )
  })

  it('prefetches thread detail data for Thread detail screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/thread/123') })
    flushIdleWork()

    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.thread.detail(123),
      { staleTime: 1000, retry: false }
    )
  })

  it('prefetches session list data for History screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/history') })
    flushIdleWork()

    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.session.pages(),
      { staleTime: 1000, retry: false }
    )
  })

  it('prefetches session detail data for Session screen', () => {
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/sessions/456') })
    flushIdleWork()

    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.session.detail(456),
      { staleTime: 1000, retry: false }
    )
  })

  it('does not prefetch data for non-retained routes', () => {
    // Using a non-retained route such as '/crossovers' with prefetch enabled
    renderHook(() => useRoutePrefetch(true), { wrapper: wrapper('/crossovers') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
    expect(mockPrefetchQuery).not.toHaveBeenCalled()
  })

  it('does not prefetch data when prefetching is disabled', () => {
    renderHook(() => useRoutePrefetch(false), { wrapper: wrapper('/') })
    flushIdleWork()

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
    expect(mockPrefetchQuery).not.toHaveBeenCalled()
  })

  it('deduplicates data prefetching across route changes while the screen is mounted', () => {
    const { rerender } = renderHook(({ enabled }) => useRoutePrefetch(enabled), {
      initialProps: { enabled: true },
      wrapper: wrapper('/'),
    })
    flushIdleWork()

    // First call to prefetch bootstrap data
    expect(mockPrefetchQuery).toHaveBeenCalledWith(
      queryKeys.roll.bootstrap(),
      { staleTime: 1000, retry: false }
    )
    mockPrefetchQuery.mockClear()

    // Second call should not prefetch again due to deduplication
    rerender({ enabled: true })
    flushIdleWork()

    expect(mockPrefetchQuery).not.toHaveBeenCalled()
  })
})
