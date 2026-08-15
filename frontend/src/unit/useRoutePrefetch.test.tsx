import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

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
  })

  it('deduplicates across route changes while the screen is mounted', () => {
    const { rerender } = renderHook(({ enabled }) => useRoutePrefetch(enabled), {
      initialProps: { enabled: true },
      wrapper: wrapper('/queue'),
    })
    flushIdleWork()

    rerender({ enabled: true })
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
  })
})
