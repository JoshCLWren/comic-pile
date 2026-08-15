import { routeModules } from '../routes/routeModules'
import type { RouteModuleKey } from '../routes/routeModules'

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

/**
 * Retained screens deliberately excluded from chunk prefetching because no
 * measured navigation benefit justifies the speculative fetch:
 * Crossovers, What's New, Help, and Glossary are low-frequency, static, or
 * non-primary destinations.
 */

const IDLE_TIMEOUT_MS = 4000
const FALLBACK_DELAY_MS = 800

const prefetchedChunks = new Set<RouteModuleKey>()

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
 * Schedules chunk prefetching for the likely next destinations from the given
 * current pathname. Returns a cancel function; calling it before the idle work
 * flushes prevents any fetch.
 */
export function scheduleRoutePrefetch(pathname: string): RoutePrefetchCancel {
  const chunks = matchLikelyNext(pathname)
  if (!chunks || chunks.length === 0) return () => undefined

  const pending = scheduleIdle(() => {
    for (const chunk of chunks) {
      prefetchRouteChunk(chunk)
    }
  }, IDLE_TIMEOUT_MS)

  return () => pending.cancel()
}

/** Test hook: clears the per-lifetime prefetch dedup set. */
export function resetRoutePrefetchState(): void {
  prefetchedChunks.clear()
}
