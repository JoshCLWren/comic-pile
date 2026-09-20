import type { QueryClient } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import type { Thread, ThreadListResponse, Issue } from '../types'
import type { IssueListResponse } from '../services/api-issues'
import type { ContinuityPlan } from '../services/api-continuity-plans'
import type { CustomCBL, CustomCBLListItem } from '../services/api-custom-cbl'
import type { IssueMutationSnapshot } from '../pages/thread-detail/issueMutationState'
import { queryKeys } from './queryKeys'
import { isObject } from '../utils/runtimeChecks'

/**
 * Centralized cache effects for all React Query mutations in ComicPile.
 * 
 * ALL cache writes, invalidations, and optimistic updates must use these helpers.
 * Direct calls to `setQueryData`, `invalidateQueries`, or `removeQueries` outside
 * of this module are prohibited in production code.
 * 
 * Intentional exceptions:
 * - `useRollBootstrap.ts` reconciliation events: The real-time reconciliation system
 *   requires direct `setQueryData` calls to update the bootstrap cache immediately
 *   when external events occur. This is explicitly documented and justified by the
 *   real-time nature of the reconciliation system.
 */

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
 * Refresh the minimal auth-resume set after a bfcache/visibility resume
 * recovery (`ResumeRecovery`, #2582). Scoped to the retained resume
 * resources — current session, roll bootstrap, and queue pages — so recovery
 * reconciles data without the unscoped `invalidateQueries()` blast that used
 * to churn deferred layout underneath an in-progress scroll restore.
 */
export async function invalidateAfterResumeRecovery(client: QueryClient): Promise<void> {
  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
  ])
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

export async function invalidateReadingPlans(client: QueryClient): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.readingPlans.all })
  // Plan create/update/delete recompiles eligibility rules that Roll/Queue/session consume.
  await invalidateAfterQueueMovement(client)
}

/**
 * Apply a committed reading plan to the cache and refresh dependent queries.
 * Centralizes the pattern used in useReadingPlans.ts useSaveReadingPlan and
 * CustomCBLBuilder.tsx apply mutation.
 */
export async function applyCommittedReadingPlan(
  client: QueryClient,
  plan: ContinuityPlan,
): Promise<void> {
  client.setQueryData(queryKeys.readingPlans.detail(plan.id), plan)
  await client.invalidateQueries({
    queryKey: queryKeys.readingPlans.list(),
    exact: true,
  })
  await invalidateAfterQueueMovement(client)
}

/**
 * @deprecated Use `applyCommittedReadingPlan` instead.
 */
export async function applyCommittedReadingPlanUpdate(
  client: QueryClient,
  plan: ContinuityPlan,
): Promise<void> {
  return applyCommittedReadingPlan(client, plan)
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
    if (!old || !isObject(old)) {
      // SAFETY: non-object cache values are intentionally discarded unchanged; the never widen preserves the cache value type.
      return old as never
    }
    // SAFETY: isObject(old) above narrows the cache value to a record shape that supports the 'in' probe.
    const record = old as Record<string, string | null>
    if (!('image_url' in record)) {
      // SAFETY: the 'in' check above confirms the record already has the image_url key before reading it.
      return old as never
    }
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

/**
 * Boolean guard for the paged (infinite) issue cache shape. The
 * `queryKeys.thread.issuePages` prefix also hosts the flattened all-issues
 * array (`queryKeys.thread.issuePagesAll`), so shape-matching updaters must
 * skip array-valued queries instead of treating them as `{ pages }` data.
 */
function isIssuePagesInfiniteData(data: unknown): data is InfiniteData<IssueListResponse> {
  return (
    isObject(data)
    && Array.isArray(data.pages)
    && data.pages.every((page) => isObject(page) && Array.isArray(page.issues))
  )
}

/**
 * Apply an authoritative issue read-status result to the cache so the thread
 * detail view reflects a toggle without refetching every loaded issue page.
 *
 * The snapshot carries the reconciled visible issues plus the server-refreshed
 * thread; the issues are patched in-place across every loaded infinite page
 * (keyed via `queryKeys.thread.issuePages`) and the thread is pushed through
 * `applyEditedThreadToQueuePages` (detail, summary, and queue rows).
 */
export function applyIssueReadSnapshotToCache(
  client: QueryClient,
  snapshot: IssueMutationSnapshot,
): void {
  const { issues: snapshotIssues, thread: updatedThread } = snapshot
  const issuesById = new Map(snapshotIssues.map((issue) => [issue.id, issue]))

  client.setQueriesData<InfiniteData<IssueListResponse>>(
    {
      queryKey: queryKeys.thread.issuePages(updatedThread.id),
      predicate: (query) => isIssuePagesInfiniteData(query.state.data),
    },
    (old) => {
      if (!old) return old
      return {
        ...old,
        pages: old.pages.map((page) => ({
          ...page,
          issues: page.issues.map((issue: Issue) => issuesById.get(issue.id) ?? issue),
        })),
      }
    },
  )

  applyEditedThreadToQueuePages(client, updatedThread)
}

/**
 * Refresh the retained data a DependencyBuilder change can affect: the thread
 * detail/summary, dependency and crossover groups, reading orders, current
 * session, and queue pages. Replaces the previous one-off thread refetch in the
 * thread detail view.
 */
export async function invalidateAfterDependencyChange(
  client: QueryClient,
  threadId: number,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.dependencies.all }),
    client.invalidateQueries({ queryKey: queryKeys.crossover.all }),
    client.invalidateQueries({ queryKey: queryKeys.thread.detail(threadId), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.thread.summary(threadId), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.readingOrders.forThread(threadId) }),
    client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
  ])
}

/**
 * Apply a created custom CBL to the cache and refresh the list view.
 * Mirrors the pattern used in CustomCBLBuilder.tsx create mutation.
 */
export async function applyCreatedCustomCBL(
  client: QueryClient,
  created: CustomCBL,
): Promise<void> {
  client.setQueryData(queryKeys.customCBLs.detail(created.id), created)
  await client.invalidateQueries({ queryKey: queryKeys.customCBLs.list(), exact: true })
}

/**
 * Apply an updated custom CBL to the cache and refresh the list view.
 * Mirrors the pattern used in CustomCBLBuilder.tsx save mutation.
 */
export async function applyUpdatedCustomCBL(
  client: QueryClient,
  saved: CustomCBL,
): Promise<void> {
  client.setQueryData(queryKeys.customCBLs.detail(saved.id), saved)
  await client.invalidateQueries({ queryKey: queryKeys.customCBLs.list(), exact: true })
}

/**
 * Remove a custom CBL from the cache and refresh the list view.
 * Mirrors the pattern used in CustomCBLBuilder.tsx delete mutation.
 */
export async function applyDeletedCustomCBL(
  client: QueryClient,
  deletedId: number,
): Promise<void> {
  client.removeQueries({ queryKey: queryKeys.customCBLs.detail(deletedId), exact: true })
  await client.invalidateQueries({ queryKey: queryKeys.customCBLs.list(), exact: true })
}

/**
 * Invalidate all queries affected by session recovery in ResumeRecovery.
 * Replaces the blanket `invalidateQueries()` call with targeted invalidation.
 */
export async function invalidateSessionRecoveryCache(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.roll.bootstrap(), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({ queryKey: queryKeys.readingPlans.all }),
  ])
}

/**
 * Invalidate the identity-inbox list cache after a mutation (confirm, reject,
 * defer, skip) so the inbox refetches the updated item set.
 */
export async function invalidateIdentityInbox(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.identityInbox.all })
}

export type IssueCacheRollback = () => void

/**
 * Optimistically update an issue's status in the cache.
 * Used by useToggleIssueStatus mutation.
 */
export function optimisticallyUpdateIssueStatus(
  client: QueryClient,
  threadId: number,
  issue: Issue,
  nextStatus: 'read' | 'unread',
): IssueCacheRollback {
  const allIssuesKey = queryKeys.thread.issuePagesAll(threadId)
  const previousIssues = client.getQueryData<Issue[]>(allIssuesKey)

  if (previousIssues) {
    const updatedIssue: Issue = {
      ...issue,
      status: nextStatus,
      read_at: nextStatus === 'read' ? new Date().toISOString() : null,
    }
    client.setQueryData<Issue[]>(
      allIssuesKey,
      previousIssues.map((i) => (i.id === issue.id ? updatedIssue : i)),
    )
  }

  return () => {
    if (previousIssues) {
      client.setQueryData(allIssuesKey, previousIssues)
    }
  }
}

/**
 * Optimistically delete an issue from the cache.
 * Used by useDeleteIssue mutation.
 */
export function optimisticallyDeleteIssue(
  client: QueryClient,
  threadId: number,
  issueId: number,
): IssueCacheRollback {
  const allIssuesKey = queryKeys.thread.issuePagesAll(threadId)
  const previousIssues = client.getQueryData<Issue[]>(allIssuesKey)

  if (previousIssues) {
    client.setQueryData<Issue[]>(
      allIssuesKey,
      previousIssues.filter((i) => i.id !== issueId),
    )
  }

  return () => {
    if (previousIssues) {
      client.setQueryData(allIssuesKey, previousIssues)
    }
  }
}

/**
 * Optimistically reorder issues in the cache.
 * Used by useReorderIssues mutation.
 */
export function optimisticallyReorderIssues(
  client: QueryClient,
  threadId: number,
  issueIds: number[],
): IssueCacheRollback {
  const allIssuesKey = queryKeys.thread.issuePagesAll(threadId)
  const previousIssues = client.getQueryData<Issue[]>(allIssuesKey)

  if (previousIssues) {
    const issueMap = new Map(previousIssues.map((i) => [i.id, i]))
    const reordered = issueIds.flatMap((id) => {
      const issue = issueMap.get(id)
      return issue ? [issue] : []
    })
    client.setQueryData<Issue[]>(allIssuesKey, reordered)
  }

  return () => {
    if (previousIssues) {
      client.setQueryData(allIssuesKey, previousIssues)
    }
  }
}

/**
 * Invalidate crossover group caches after a mutation that changes group
 * membership or metadata (create, rename, delete, addMember, addIssueRange,
 * removeMember). The list query is invalidated so the CrossoversPage refetches
 * the full group list with updated membership counts.
 */
export async function invalidateAfterCrossoverMutation(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.crossover.all })
}

/**
 * Apply a migrated thread to the cache and invalidate thread list.
 * Used after a thread is migrated to issue tracking.
 */
export async function applyMigratedThreadCache(
  client: QueryClient,
  thread: Thread,
): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)
  await client.invalidateQueries({ queryKey: queryKeys.thread.list() })
}
