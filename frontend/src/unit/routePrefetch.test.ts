import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'

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

import {
  prefetchRouteChunk,
  scheduleRoutePrefetch,
  resetRoutePrefetchState,
} from '../query/routePrefetch'
import { routeModules } from '../routes/routeModules'

const FALLBACK_DELAY_MS = 800

function flushIdleWork(): void {
  vi.advanceTimersByTime(FALLBACK_DELAY_MS + 1)
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

describe('prefetchRouteChunk', () => {
  it('deduplicates repeated prefetch of the same chunk', () => {
    prefetchRouteChunk('queue')
    prefetchRouteChunk('queue')

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('prefetches distinct chunks independently', () => {
    prefetchRouteChunk('queue')
    prefetchRouteChunk('roll')

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
  })

  it('swallows loader failures without surfacing errors', async () => {
    routeLoaders.queue.mockRejectedValueOnce(new Error('warm-up failed'))
    expect(() => prefetchRouteChunk('queue')).not.toThrow()
    await Promise.resolve()
    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })
})

describe('scheduleRoutePrefetch scoping', () => {
  it('prefetches only the likely next chunks from the Roll screen', () => {
    scheduleRoutePrefetch('/')
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.roll).not.toHaveBeenCalled()
    expect(routeLoaders.threadDetail).not.toHaveBeenCalled()
    expect(routeLoaders.history).not.toHaveBeenCalled()
    expect(routeLoaders.session).not.toHaveBeenCalled()
    expect(routeLoaders.crossovers).not.toHaveBeenCalled()
  })

  it('prefetches Roll and thread detail chunks from the Queue screen', () => {
    scheduleRoutePrefetch('/queue')
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
    expect(routeLoaders.history).not.toHaveBeenCalled()
  })

  it('prefetches the queue chunk from a thread detail path', () => {
    scheduleRoutePrefetch('/thread/42')
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('prefetches the session chunk from the history screen', () => {
    scheduleRoutePrefetch('/history')
    flushIdleWork()

    expect(routeLoaders.session).toHaveBeenCalledTimes(1)
  })

  it('prefetches the history chunk from a session path', () => {
    scheduleRoutePrefetch('/sessions/9')
    flushIdleWork()

    expect(routeLoaders.history).toHaveBeenCalledTimes(1)
  })

  it('does not prefetch anything from retained low-frequency screens', () => {
    for (const path of ['/crossovers', '/whats-new', '/help', '/glossary']) {
      scheduleRoutePrefetch(path)
      flushIdleWork()
    }

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
  })
})

describe('scheduleRoutePrefetch cancellation and stale behavior', () => {
  it('cancels pending prefetch work before it flushes', () => {
    const cancel = scheduleRoutePrefetch('/')
    cancel()
    flushIdleWork()

    expect(routeLoaders.queue).not.toHaveBeenCalled()
  })

  it('does not re-prefetch chunks already warmed by an earlier schedule', () => {
    scheduleRoutePrefetch('/')
    flushIdleWork()

    scheduleRoutePrefetch('/queue')
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('does not invoke loaders before idle work flushes', () => {
    scheduleRoutePrefetch('/')
    expect(routeLoaders.queue).not.toHaveBeenCalled()
  })
})

describe('collection route exclusion', () => {
  it('exposes no collection route module to prefetch', () => {
    const keys = Object.keys(routeModules)
    expect(keys.some((key) => key.toLowerCase().includes('collection'))).toBe(false)
    expect(keys.some((key) => key.toLowerCase().includes('library'))).toBe(false)
  })
})
