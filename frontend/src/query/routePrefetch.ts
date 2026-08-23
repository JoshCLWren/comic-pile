import { routeModules } from '../routes/routeModules'
import type { RouteModuleKey } from '../routes/routeModules'
import { queryClient } from './queryClient'
import { queueThreadsQueryOptions } from '../hooks/useQueue'

/**
 * Retained-route chunk and bounded-data prefetching.
 *
 * Prefetching here is intentionally limited to retained, likely navigation
 * paths. Collections were removed in #636 and no collection route key exists
 * in `routeModules`, so collection chunks can never be prefetched.
 *
 * Bounded *data* prefetching is limited to the one retained screen that reads
 * through a TanStack Query contract today: the Queue list first page
 * (`useQueueThreads` via `useInfiniteQuery`). Roll bootstrap, thread detail,
 * and session reads still flow through legacy hooks that bypass the query
 * cache, so prefetching those keys would fetch into a cache no consumer reads.
 * Those keys stay excluded until their screens adopt bounded query contracts;
 * this keeps the "no broad full-library hydration" guarantee intact (#706).
 *
 * Guarantees:
 * - Bounded: one module fetch per likely-next chunk plus at most one bounded
 *   Queue first-page request, never a library sweep.
 * - Deduplicated: each chunk and each warmed key is requested at most once
 *   per client lifetime.
 * - Cancellable: `scheduleRoutePrefetch` returns a cancel function; pending
 *   idle work is dropped on unmount or route change before any fetch starts.
 * - Stale-safe: work that has been loaded or prefetched is never requested
 *   again, so repeated render cycles cannot re-trigger network work.
 */

export interface RoutePrefetchCancel {
  (): void
}

/** Bounded data warm-ups that have a live cache consumer on a retained screen. */
type BoundedDataPrefetch = 'queueFirstPage'

/** Chunks worth warming from each retained screen, with the navigation path each serves. */
const LIKELY_NEXT_CHUNKS: ReadonlyArray<{
  path: string
  from: string
  chunks: readonly RouteModuleKey[]
  /** Optional bounded data worth warming alongside these chunks. */
  data?: BoundedDataPrefetch
}> = [
  {
    path: '/',
    from: 'Roll',
    // Queue is the primary secondary destination (nav bar and the Roll action
    // sheet "Edit" both route there).
    chunks: ['queue'],
    // The Queue screen reads its first page through the canonical
    // `queue.pages` infinite-query key, so warming it removes the list
    // round-trip from the most likely navigation.
    data: 'queueFirstPage',
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
    data: 'queueFirstPage',
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
 *
 * Retained screens deliberately excluded from *data* prefetching because
 * their reads bypass the TanStack Query cache (legacy hooks): Roll bootstrap,
 * thread detail/summaries, session current/pages/detail. A warmed entry for
 * those keys has no consumer until the screens migrate.
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
 * Gets the bounded data warm-up scheduled for the given current pathname, or
 * null when no consumer-backed data should be prefetched from this screen.
 */
function matchLikelyNextData(pathname: string): BoundedDataPrefetch | null {
  const path = pathname.split('?')[0]
  for (const candidate of LIKELY_NEXT_CHUNKS) {
    if (!candidate.data) continue
    if (candidate.path === path) return candidate.data
    if (
      candidate.path === '/thread/:id'
      && /^\/thread\/\d+$/i.test(path)
    ) {
      return candidate.data
    }
    if (
      candidate.path === '/sessions/:id'
      && /^\/sessions\/\d+$/i.test(path)
    ) {
      return candidate.data
    }
  }
  return null
}

/**
 * Warms the bounded Queue list first page through the exact options consumed
 * by `useInfiniteQuery` in `useQueueThreads`, so navigation to `/queue`
 * renders immediately from cache while the entry is fresh.
 *
 * Idempotent: the page is requested once per client lifetime keyed by the
 * canonical query key. Errors are swallowed; the live screen retries through
 * its own query when it mounts.
 */
export function prefetchQueueFirstPage(): void {
  const { queryKey } = queueThreadsQueryOptions()
  const dedupeKey = JSON.stringify(queryKey)
  if (prefetchedData.has(dedupeKey)) return

  prefetchedData.add(dedupeKey)
  queryClient
    .prefetchInfiniteQuery(queueThreadsQueryOptions())
    .catch(() => {
      // A failed warm-up must not affect navigation; the Queue screen will
      // fetch its own first page on mount.
    })
}

/**
 * Schedules chunk and bounded-data prefetching for the likely next destinations
 * from the given current pathname. Returns a cancel function; calling it before
 * the idle work flushes prevents any fetch.
 */
export function scheduleRoutePrefetch(pathname: string): RoutePrefetchCancel {
  const chunks = matchLikelyNext(pathname)
  const data = matchLikelyNextData(pathname)

  if ((!chunks || chunks.length === 0) && !data) return () => undefined

  const pending = scheduleIdle(() => {
    if (chunks && chunks.length > 0) {
      for (const chunk of chunks) {
        prefetchRouteChunk(chunk)
      }
    }
    if (data === 'queueFirstPage') {
      prefetchQueueFirstPage()
    }
  }, IDLE_TIMEOUT_MS)

  return () => pending.cancel()
}

/** Test hook: clears the per-lifetime prefetch dedup sets. */
export function resetRoutePrefetchState(): void {
  prefetchedChunks.clear()
  prefetchedData.clear()
}
