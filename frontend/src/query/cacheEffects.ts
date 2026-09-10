import type { QueryClient } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import type { Thread, ThreadListResponse } from '../types'
import { queryKeys } from './queryKeys'
import { isObject } from '../utils/runtimeChecks'

export type ThreadCacheRollback = () => void

export function optimisticallyUpdateThreadCache(
  client: QueryClient,
  threadId: number,
  update: (thread: Thread) => Thread,
): ThreadCacheRollback {
  const detailKey = queryKeys.thread.detail(threadId)
  const summaryKey = queryKeys.thread.summary(threadId)
  const previousDetail = client.getQueryData<Thread>(detailKey)
  const previousSummary = client.getQueryData<Thread>(summaryKey)

  if (previousDetail) {
    client.setQueryData(detailKey, update(previousDetail))
  }
  if (previousSummary) {
    client.setQueryData(summaryKey, update(previousSummary))
  }

  return () => {
    if (previousDetail) {
      client.setQueryData(detailKey, previousDetail)
    } else {
      client.removeQueries({ queryKey: detailKey, exact: true })
    }

    if (previousSummary) {
      client.setQueryData(summaryKey, previousSummary)
    } else {
      client.removeQueries({ queryKey: summaryKey, exact: true })
    }
  }
}

export async function applyRatedThreadCache(
  client: QueryClient,
  thread: Thread,
): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)

  await client.invalidateQueries({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
}

export async function applyUpdatedThreadCache(
  client: QueryClient,
  thread: Thread,
): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)

  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
  ])
}

export async function invalidateAfterIssueEdit(
  client: QueryClient,
  threadId: number,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.thread.issuePages(threadId),
    }),
    client.invalidateQueries({
      queryKey: queryKeys.thread.detail(threadId),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.thread.summary(threadId),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.queue.pages(),
    }),
  ])
}

export async function invalidateCurrentSessionAfterSnooze(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
}

/**
 * Drop the cached roll bootstrap after a manual thread selection
 * (`POST /threads/{id}/set-pending`) so the next Roll mount fetches the new
 * pending thread instead of replaying a still-fresh snapshot with no pending
 * selection (#2153). `resetQueries` (not `invalidateQueries`) is deliberate:
 * an invalidated-but-cached bootstrap would still be handed to Roll on mount
 * and briefly render the empty dice view before the refetch settles.
 */
export async function resetRollBootstrapAfterManualSelection(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.resetQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
  ])
}

export async function invalidateAfterQueueMovement(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    // Reset (not invalidate) the paginated Queue loader: re-fetching already
    // loaded pages through their pre-mutation cursors can duplicate or skip
    // rows after ordering shifts (#933). Resetting drops every loaded page so
    // each active list re-requests exactly one bounded first page.
    client.resetQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
  ])
}

/**
 * Invalidate all Queue-affecting queries after a mutation that changes queue
 * ordering or membership (create, delete, reposition, shuffle, snooze,
 * unsnooze, reactivate). TanStack Query refetches invalidated queries
 * automatically — callers must not also call `refetch()`.
 *
 * This is intentionally an alias of `invalidateAfterQueueMovement` — both
 * operations refresh the same three retained resources (queue pages, current
 * session, roll bootstrap) and must stay in sync.
 */
export async function invalidateAfterQueueMutation(
  client: QueryClient,
): Promise<void> {
  return invalidateAfterQueueMovement(client)
}

/**
 * Invalidate only the `comicVine.issueIntelligence(issueId)` cache bucket after
 * a ComicVine identity correction/replacement so the rating view refetches the
 * freshly confirmed issue metadata without clearing unrelated caches.
 */
export async function invalidateComicVineIssueIntelligence(
  client: QueryClient,
  issueId: number,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.comicVine.issueIntelligence(issueId),
    exact: true,
  })
}

/**
 * Update the cached `image_url` for an issue's ComicVine intelligence in-place
 * so the newly selected cover renders immediately after a correction. The
 * subsequent invalidation/refetch confirms the optimistic value from the server.
 */
export function applyComicVineCorrectionOptimistically(
  client: QueryClient,
  issueId: number,
  imageUrl: string | null,
): void {
  if (imageUrl === undefined) return
  client.setQueryData(queryKeys.comicVine.issueIntelligence(issueId), (old: unknown) => {
    // SAFETY: non-object cache values are intentionally discarded unchanged; the never widen preserves the cache value type.
    if (!old || !isObject(old)) return old as never
    // SAFETY: isObject(old) above narrows the cache value to a record shape that supports the 'in' probe.
    const record = old as Record<string, unknown>
    // SAFETY: the 'in' check above confirms the record already has the image_url key before reading it.
    if (!('image_url' in record)) return old as never
    // SAFETY: isObject(old) and the 'in' probe guarantee the spread source is an assignable object.
    return { ...(old as object), image_url: imageUrl } as never
  })
}

/**
 * Update a single thread's metadata in every loaded Queue infinite-query page
 * in-place. Use this for mutations that change thread metadata (title, format,
 * notes, issues_remaining, rating) without changing queue ordering or membership.
 *
 * Returns immediately — no network refetch is triggered for the Queue list.
 */
export function applyEditedThreadToQueuePages(
  client: QueryClient,
  updatedThread: Thread,
): void {
  client.setQueriesData<InfiniteData<ThreadListResponse>>(
    { queryKey: queryKeys.queue.pages() },
    (old) => {
      if (!old) return old
      return {
        ...old,
        pages: old.pages.map((page) => ({
          ...page,
          threads: page.threads.map((t) =>
            t.id === updatedThread.id ? { ...t, ...updatedThread } : t,
          ),
        })),
      }
    },
  )

  client.setQueryData(queryKeys.thread.detail(updatedThread.id), updatedThread)
  client.setQueryData(queryKeys.thread.summary(updatedThread.id), updatedThread)
}