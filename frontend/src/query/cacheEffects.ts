import type { QueryClient } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import type { Thread, ThreadListResponse } from '../types'
import { queryKeys } from './queryKeys'

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