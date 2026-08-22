import { routeModules } from '../routes/routeModules'
import type { RouteModuleKey } from '../routes/routeModules'
import { queryClient } from './queryClient'
import { queryKeys } from './queryKeys'
import type { QueueSort } from './queryKeys'
import { QUEUE_PAGE_SIZE } from '../hooks/useQueue'

/**
 * Retained-route chunk prefetching.
 *
 * Prefetching here is intentionally limited to route *chunks* for retained,
 * likely navigation paths. Collections were removed in #636 and no collection
 * route key exists in `routeModules`, so collection chunks can never be
 * prefetched.
 *
 * Bounded data prefetching (TanStack Query keys such as
 * `queryKeys.roll.bootstrap()`, `queryKeys.session.current()`, and
 * `queryKeys.thread.detail(id)`) is deferred until the bounded screen-specific
 * read contracts from #696/#703 land. The retained screens still read through
 * legacy custom hooks, so prefetching data today would fetch into a cache no
 * consumer reads and violate the "no broad full-library hydration" and
 * "bounded contracts" guarantees.
 *
 * Guarantees:
 * - Bounded: one module fetch per likely-next chunk, never a library sweep.
 * - Deduplicated: each chunk is prefetched at most once per client lifetime.
 * - Cancellable: `scheduleRoutePrefetch` returns a cancel function; pending
 *   idle work is dropped on unmount or route change before any fetch starts.
 * - Stale-safe: a chunk that has been loaded or prefetched is never requested
 *   again, so repeated render cycles cannot re-trigger network work.
 */

export interface RoutePrefetchCancel {
  (): void
}

/** Bounded data prefetching for retained screens. */
interface BoundedDataPrefetch {
  path: string
  from: string
  /** Query key to prefetch for this path */
  queryKey: unknown[]
}

/** Chunks worth warming from each retained screen, with the navigation path each serves. */
const LIKELY_NEXT_CHUNKS: ReadonlyArray<{
  path: string
  from: string
  chunks: readonly RouteModuleKey[]
}> = [
  {
    path: '/',
    from: 'Roll',
    // Queue is the primary secondary destination (nav bar and the Roll action
    // sheet "Edit" both route there).
    chunks: ['queue'],
  },
  {
    path: '/queue',
    from: 'Queue',
    // "Read" returns to the Roll screen and every card opens a thread detail.
    chunks: ['roll', 'threadDetail'],
  },
  {
    path: '/thread/:id',
    from: 'Thread detail',
    // The dominant back-navigation target after inspecting a thread.
    chunks: ['queue'],
  },
  {
    path: '/history',
    from: 'History',
    // Session rows open the session screen.
    chunks: ['session'],
  },
  {
    path: '/sessions/:id',
    from: 'Session',
    // Back-navigation target for session browsing.
    chunks: ['history'],
  },
]

/** Bounded data worth warming from each retained screen, with the navigation path each serves. */
const LIKELY_NEXT_DATA: ReadonlyArray<BoundedDataPrefetch> = [
  {
    path: '/',
    from: 'Roll',
    // Bootstrap data is needed to initialize the roll screen
    queryKey: queryKeys.roll.bootstrap(),
  },
  {
    path: '/queue',
    from: 'Queue',
    // First page of queue list is needed to display threads
    queryKey: queryKeys.queue.list({ search: undefined, sort: 'position' as QueueSort, pageSize: QUEUE_PAGE_SIZE }),
  },
  {
    path: '/thread/:id',
    from: 'Thread detail',
    // Thread detail data is needed to display the thread
    // Note: The actual thread ID will be extracted from the pathname
    queryKey: (_pathname: string) => {
      const match = _pathname.match(/^\/thread\/(\d+)$/i)
      if (match) {
        return queryKeys.thread.detail(Number(match[1]))
      }
      return null
    },
  },
  {
    path: '/history',
    from: 'History',
    // First page of session list is needed to display history
    queryKey: queryKeys.session.pages(),
  },
  {
    path: '/sessions/:id',
    from: 'Session',
    // Session detail data is needed to display the session
    // Note: The actual session ID will be extracted from the pathname
    queryKey: (_pathname: string) => {
      const match = _pathname.match(/^\/sessions\/(\d+)$/i)
      if (match) {
        return queryKeys.session.detail(Number(match[1]))
      }
      return null
    },
  },
]

/**
 * Retained screens deliberately excluded from chunk prefetching because no
 * measured navigation benefit justifies the speculative fetch:
 * Crossovers, What's New, Help, and Glossary are low-frequency, static, or
 * non-primary destinations.
 */

const IDLE_TIMEOUT_MS = 4000
const FALLBACK_DELAY_MS = 800

const prefetchedChunks = new Set<RouteModuleKey>()
const prefetchedData = new Set<string>()

type IdleHandle = { cancel: () => void }

function scheduleIdle(task: () => void, timeoutMs: number): IdleHandle {
  const requestIdleCallback = (globalThis as { requestIdleCallback?: typeof globalThis.requestIdleCallback }).requestIdleCallback
  if (typeof requestIdleCallback === 'function') {
    const id = requestIdleCallback(task, { timeout: timeoutMs })
    return { cancel: () => globalThis.cancelIdleCallback(id) }
  }

  const id = globalThis.setTimeout(task, FALLBACK_DELAY_MS)
  return { cancel: () => globalThis.clearTimeout(id) }
}

/**
 * Starts (or reuses) the fetch of a retained route chunk.
 *
 * Idempotent: a chunk is requested once per client lifetime. Errors are
 * swallowed so a prefetch failure never surfaces to the active screen.
 */
export function prefetchRouteChunk(key: RouteModuleKey): void {
  if (prefetchedChunks.has(key)) return

  const loader = routeModules[key]
  if (!loader) return

  prefetchedChunks.add(key)
  loader().catch(() => {
    // A failed warm-up must not affect navigation; the lazy route will retry
    // its own dynamic import on mount.
  })
}

/**
 * Prefetches bounded data for a given query key.
 *
 * Idempotent: the data is requested once per client lifetime based on the
 * stringified query key. Errors are swallowed so a prefetch failure never
 * surfaces to the active screen.
 */
export function prefetchBoundedData(queryKey: unknown[]): void {
  // Create a stable string key for deduplication
  const key = JSON.stringify(queryKey)
  if (prefetchedData.has(key)) return

  prefetchedData.add(key)
  queryClient.prefetchQuery({
    queryKey,
    // Prefetch with a short stale time since this is speculative
    staleTime: 1000, // 1 second
    // Don't retry prefetch failures - let the actual request handle retries
    retry: false,
  }).catch(() => {
    // A failed warm-up must not affect navigation; the actual query will retry
  })
}

function matchLikelyNext(pathname: string): readonly RouteModuleKey[] | null {
  const path = pathname.split('?')[0]
  for (const candidate of LIKELY_NEXT_CHUNKS) {
    if (candidate.path === path) return candidate.chunks
    if (
      candidate.path === '/thread/:id'
      && /^\/thread\/\d+$/i.test(path)
    ) {
      return candidate.chunks
    }
    if (
      candidate.path === '/sessions/:id'
      && /^\/sessions\/\d+$/i.test(path)
    ) {
      return candidate.chunks
    }
  }
  return null
}

/**
 * Gets the bounded data to prefetch for the likely next destinations from the
 * given current pathname. Returns null if no data should be prefetched.
 */
function matchLikelyNextData(pathname: string): null | unknown[][] {
  const path = pathname.split('?')[0]
  
  for (const candidate of LIKELY_NEXT_DATA) {
    if (candidate.path === path) {
      const queryKey = candidate.queryKey
      return queryKey !== null ? [queryKey] : null
    }
    
    if (
      candidate.path === '/thread/:id'
      && /^\/thread\/\d+$/i.test(path)
    ) {
      const queryKey = typeof candidate.queryKey === 'function' 
        ? candidate.queryKey(pathname) 
        : candidate.queryKey
      return queryKey !== null ? [queryKey] : null
    }
    
    if (
      candidate.path === '/sessions/:id'
      && /^\/sessions\/\d+$/i.test(path)
    ) {
      const queryKey = typeof candidate.queryKey === 'function' 
        ? candidate.queryKey(pathname) 
        : candidate.queryKey
      return queryKey !== null ? [queryKey] : null
    }
  }
  
  return null
}

/**
 * Schedules chunk and bounded data prefetching for the likely next destinations from the given
 * current pathname. Returns a cancel function; calling it before the idle work
 * flushes prevents any fetch.
 */
export function scheduleRoutePrefetch(pathname: string): RoutePrefetchCancel {
  const chunks = matchLikelyNext(pathname)
  const dataKeys = matchLikelyNextData(pathname)
  
  // If nothing to prefetch, return empty cancel function
  if ((!chunks || chunks.length === 0) && (!dataKeys || dataKeys.length === 0)) {
    return () => undefined
  }

  const pending = scheduleIdle(() => {
    // Prefetch chunks
    if (chunks && chunks.length > 0) {
      for (const chunk of chunks) {
        prefetchRouteChunk(chunk)
      }
    }
    
    // Prefetch bounded data
    if (dataKeys && dataKeys.length > 0) {
      for (const queryKey of dataKeys) {
        prefetchBoundedData(queryKey)
      }
    }
  }, IDLE_TIMEOUT_MS)

  return () => pending.cancel()
}

/** Test hook: clears the per-lifetime prefetch dedup set. */
export function resetRoutePrefetchState(): void {
  prefetchedChunks.clear()
  prefetchedData.clear()
}
