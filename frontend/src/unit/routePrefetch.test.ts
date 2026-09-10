import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import {
  prefetchQueueFirstPage,
  prefetchRouteChunk,
  scheduleRoutePrefetch,
  resetRoutePrefetchState,
} from '../query/routePrefetch'
import type { RoutePrefetchDependencies } from '../query/routePrefetch'
import { queueThreadsQueryOptions } from '../hooks/useQueue'

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
  prefetchInfiniteQuery.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('prefetchRouteChunk', () => {
  it('deduplicates repeated prefetch of the same chunk', () => {
    prefetchRouteChunk('queue', deps)
    prefetchRouteChunk('queue', deps)

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('prefetches distinct chunks independently', () => {
    prefetchRouteChunk('queue', deps)
    prefetchRouteChunk('roll', deps)

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
  })

  it('swallows loader failures without surfacing errors', async () => {
    routeLoaders.queue.mockRejectedValueOnce(new Error('warm-up failed'))
    expect(() => prefetchRouteChunk('queue', deps)).not.toThrow()
    await Promise.resolve()
    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })
})

describe('scheduleRoutePrefetch scoping', () => {
  it('prefetches only the likely next chunks from the Roll screen', () => {
    scheduleRoutePrefetch('/', deps)
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
    expect(routeLoaders.roll).not.toHaveBeenCalled()
    expect(routeLoaders.threadDetail).not.toHaveBeenCalled()
    expect(routeLoaders.history).not.toHaveBeenCalled()
    expect(routeLoaders.session).not.toHaveBeenCalled()
    expect(routeLoaders.crossovers).not.toHaveBeenCalled()
  })

  it('prefetches Roll and thread detail chunks from the Queue screen', () => {
    scheduleRoutePrefetch('/queue', deps)
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
    expect(routeLoaders.history).not.toHaveBeenCalled()
  })

  it('prefetches the queue chunk from a thread detail path', () => {
    scheduleRoutePrefetch('/thread/42', deps)
    flushIdleWork()

    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('prefetches the session chunk from the history screen', () => {
    scheduleRoutePrefetch('/history', deps)
    flushIdleWork()

    expect(routeLoaders.session).toHaveBeenCalledTimes(1)
  })

  it('prefetches the history chunk from a session path', () => {
    scheduleRoutePrefetch('/sessions/9', deps)
    flushIdleWork()

    expect(routeLoaders.history).toHaveBeenCalledTimes(1)
  })

  it('does not prefetch anything from retained low-frequency screens', () => {
    for (const path of ['/crossovers', '/whats-new', '/glossary']) {
      scheduleRoutePrefetch(path, deps)
      flushIdleWork()
    }

    for (const key of routeLoaderKeys) {
      expect(routeLoaders[key]).not.toHaveBeenCalled()
    }
  })
})

describe('bounded data prefetching', () => {
  it('warms the queue first page through the canonical screen contract', () => {
    scheduleRoutePrefetch('/', deps)
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

  it('warms the queue first page from a thread detail back-navigation path', () => {
    scheduleRoutePrefetch('/thread/42', deps)
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

  it('does not warm data from screens without a cache-backed consumer', () => {
    for (const path of ['/queue', '/history', '/sessions/9']) {
      scheduleRoutePrefetch(path, deps)
      flushIdleWork()
    }

    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('does not warm data from non-retained routes', () => {
    scheduleRoutePrefetch('/crossovers', deps)
    flushIdleWork()

    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('cancels pending data warm-ups before they flush', () => {
    const cancel = scheduleRoutePrefetch('/', deps)
    cancel()
    flushIdleWork()

    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('warms each bounded key at most once per client lifetime', () => {
    prefetchQueueFirstPage(deps)
    prefetchQueueFirstPage(deps)
    scheduleRoutePrefetch('/', deps)
    flushIdleWork()
    scheduleRoutePrefetch('/thread/42', deps)
    flushIdleWork()

    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)
  })

  it('swallows warm-up failures without surfacing errors and without retrying', async () => {
    prefetchInfiniteQuery.mockRejectedValueOnce(new Error('warm-up failed'))
    expect(() => prefetchQueueFirstPage(deps)).not.toThrow()
    await Promise.resolve()
    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)

    prefetchQueueFirstPage(deps)
    expect(prefetchInfiniteQuery).toHaveBeenCalledTimes(1)
  })

  it('never fetches data before idle work flushes', () => {
    scheduleRoutePrefetch('/', deps)
    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })
})

describe('scheduleRoutePrefetch cancellation and stale behavior', () => {
  it('cancels pending prefetch work before it flushes', () => {
    const cancel = scheduleRoutePrefetch('/', deps)
    cancel()
    flushIdleWork()

    expect(routeLoaders.queue).not.toHaveBeenCalled()
    expect(prefetchInfiniteQuery).not.toHaveBeenCalled()
  })

  it('does not re-prefetch chunks already warmed by an earlier schedule', () => {
    scheduleRoutePrefetch('/', deps)
    flushIdleWork()

    scheduleRoutePrefetch('/queue', deps)
    flushIdleWork()

    expect(routeLoaders.roll).toHaveBeenCalledTimes(1)
    expect(routeLoaders.threadDetail).toHaveBeenCalledTimes(1)
    expect(routeLoaders.queue).toHaveBeenCalledTimes(1)
  })

  it('does not invoke loaders before idle work flushes', () => {
    scheduleRoutePrefetch('/', deps)
    expect(routeLoaders.queue).not.toHaveBeenCalled()
  })
})

describe('collection route exclusion', () => {
  it('exposes no collection route module to prefetch', () => {
    const keys = Object.keys(deps.routeModules)
    expect(keys.some((key) => key.toLowerCase().includes('collection'))).toBe(false)
    expect(keys.some((key) => key.toLowerCase().includes('library'))).toBe(false)
  })
})