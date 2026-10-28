import type { QueryClient } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import type { Thread, ThreadListResponse, Issue } from '../types'
import type { IssueListResponse } from '../services/api-issues'
import type { ContinuityPlan } from '../services/api-continuity-plans'
import type { CustomCBL, CustomCBLListItem } from '../services/api-custom-cbl'
import type { IssueMutationSnapshot } from '../pages/thread-detail/issueMutationState'
import { queryKeys } from './queryKeys'
import { isObject } from '../utils/runtimeChecks'
import { isTransientQueryFailure } from './outageRetryBudget'

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

/** Remove session-owned data and cancel queries before another account can read it.
 * QueryClient.clear destroys active queries (including pending retryers) and
 * removes mutation records without refetching authenticated endpoints.
 */
export function clearSessionCache(client: QueryClient): void {
  client.clear()
}

/**
 * Refetch active queries that failed during a recognized backend outage.
 *
 * Called exactly once when a request succeeds again (including the single
 * outage probe or an auth recovery). Only queries that currently hold an error
 * result are touched, and TanStack stores one Query per distinct query key, so
 * the reader gets one request per failed key — never one per observer or one
 * per invalidation. In-flight fetches are left alone.
 *
 * @param client - The app QueryClient.
 */
export async function resumeQueriesAfterOutage(client: QueryClient): Promise<void> {
  await client.refetchQueries(
    {
      type: 'active',
      predicate: (query) => {
        if (query.state.status !== 'error') {
          return false
        }
        const error = query.state.error
        // Only refetch transient failures; deterministic 4xx, auth errors, and
        // canceled requests are left to the user or manual retry.
        return isTransientQueryFailure(error)
      },
    },
    { cancelRefetch: false },
  )
}

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

  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    // A rating writes a new "After rating" snapshot (#3468). Both snapshot
    // lists read the same rows, and the History card counts them through the
    // paginated session list, so all three must stop serving the pre-rating
    // state the moment the rating commits.
    client.invalidateQueries({ queryKey: queryKeys.undo.all }),
    client.invalidateQueries({ queryKey: queryKeys.session.snapshotsAll() }),
    client.invalidateQueries({ queryKey: queryKeys.session.pages() }),
    // A rating marks the current issue read, which can clear (or create) a
    // canonical reading blocker for any series. Every reading-boundaries read
    // lives under this prefix, so refresh it with the rest of the read state.
    client.invalidateQueries({ queryKey: queryKeys.dependencies.all }),
  ])
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
    // Issue mutations can change which issues carry confirmed provider
    // credits; refresh the bulk creator-credits map alongside the pages.
    client.invalidateQueries({
      queryKey: queryKeys.thread.issueCreators(threadId),
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
    // Marking issues read (including the last unread issue) changes the
    // reader's canonical availability answer, so the "Next issue availability"
    // explanation has to stop serving the pre-edit text (#4181).
    client.invalidateQueries({
      queryKey: queryKeys.dependencies.all,
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
      queryKey: queryKeys.queue.activeCount(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
    // Exclude/restore move a series across the active-queue boundary without
    // deleting it (#3807), so the excluded library view is a fourth surface
    // that changes membership. Reset it the same way the Queue list resets:
    // a cached page still lists a series on the wrong side of the boundary.
    client.resetQueries({ queryKey: queryKeys.excluded.pages() }),
    // The Roll exclusion drill-down caches the same blocked and out-of-pool
    // rows plus their authoritative category totals (#3330). A queue change
    // that adds, removes, or reorders a series changes both the rows and the
    // order behind each offset cursor, so those pages reset instead of
    // invalidating: an invalidated page set would keep serving a deleted
    // series and the old count inside the query's stale window.
    client.resetQueries({ queryKey: queryKeys.roll.exclusions('blocked') }),
    client.resetQueries({ queryKey: queryKeys.roll.exclusions('inactive') }),
  ])
}

/**
 * Invalidate all Queue-affecting queries after a mutation that changes queue
 * ordering or membership (create, delete, reposition, shuffle, snooze,
 * unsnooze, reactivate, exclude, restore). TanStack Query refetches invalidated
 * queries automatically — callers must not also call `refetch()`.
 *
 * This is intentionally an alias of `invalidateAfterQueueMovement` — both
 * operations refresh the same retained resources (queue pages, current
 * session, roll bootstrap, excluded library pages, Roll exclusion drill-down
 * pages) and must stay in sync.
 */
export async function invalidateAfterQueueMutation(
  client: QueryClient,
): Promise<void> {
  return invalidateAfterQueueMovement(client)
}

/**
 * Drop the cached "is this ComicVine volume imported?" answer for one volume
 * after an import (#3854).
 *
 * The add-series dialog reads that status to decide between "this will create a
 * new series" and "already in your queue". The queue-movement refresh above
 * deliberately touches only the retained Queue/Session resources, so a cached
 * `imported: false` would otherwise survive a successful import and let a
 * re-selection inside the query's `staleTime` window promise a brand-new series
 * for a series the user just added. Marking the key stale forces the next
 * confirm step to ask the server again.
 */
export async function invalidateComicVineImportStatus(
  client: QueryClient,
  volumeId: number,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.comicVine.importStatus(volumeId),
    exact: true,
  })
}

/**
 * Refresh every surface an undo (or session restore) rewrites (#3194).
 *
 * An undo restores queue order/membership, the current session, the roll
 * bootstrap, and the session-history aggregates that count reads and ratings,
 * so this composes the queue-movement refresh and adds the three undo-specific
 * spaces: the paginated Session history cards (whose "N issues read" total
 * must stop counting an undone rating), the snapshot lists the next undo reads
 * from, and the session detail page's snapshot list — the same rows the
 * History card counts, so both must refresh together (#3468).
 *
 * Session detail stays on its callers' explicit refetch because that is the
 * surface the caller already owns.
 *
 * TanStack Query refetches invalidated active queries — callers must not also
 * call `refetch()` for a key this helper already refreshes.
 */
export async function invalidateAfterUndo(client: QueryClient): Promise<void> {
  await Promise.all([
    invalidateAfterQueueMovement(client),
    client.invalidateQueries({ queryKey: queryKeys.session.pages() }),
    client.invalidateQueries({ queryKey: queryKeys.session.snapshotsAll() }),
    client.invalidateQueries({ queryKey: queryKeys.undo.all }),
  ])
}

export async function invalidateReadingPlans(client: QueryClient): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.readingPlans.all })
  // Plan create/update/delete recompiles eligibility rules that Roll/Queue/session consume.
  await invalidateAfterQueueMovement(client)
}

/**
 * Refresh every surface a release-source follow or toggle rewrites.
 *
 * Both the create (follow) and enable/disable mutations invalidate the same
 * reader-view and release-source list prefixes, so they share this helper
 * instead of duplicating `invalidateQueries` calls in each hook.
 */
export async function invalidateReadingPlanReleaseSources(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.readingPlans.reader(0).slice(0, 2),
    }),
    client.invalidateQueries({
      queryKey: queryKeys.readingPlans.releaseSources(0).slice(0, 2),
    }),
  ])
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
  await client.invalidateQueries({
    queryKey: queryKeys.readingPlans.reader(plan.id),
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
 * Invalidate the `comicVine.issueIntelligence(issueId)` cache bucket for every
 * issue a series-mapping commit confirmed. The sibling mapping offer confirms
 * several issues in one request, so each confirmed issue needs its own bucket
 * invalidated without clearing unrelated caches.
 */
export async function invalidateComicVineIssueIntelligenceMany(
  client: QueryClient,
  issueIds: readonly number[],
): Promise<void> {
  await Promise.all(issueIds.map((issueId) => invalidateComicVineIssueIntelligence(client, issueId)))
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
 * Refresh creator analytics after a series' manual creator credits change so
 * add/edit/remove shows up on the Creators pages without a full page reload
 * (#3461). The creator browse list, detail, summaries, comparison, team
 * chemistry, and metric drilldowns are all server-derived from those credits,
 * so every `creators`/`creator` query prefix is invalidated.
 */
export async function invalidateAfterCreatorCreditChange(client: QueryClient): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.creators.all }),
    client.invalidateQueries({ queryKey: queryKeys.creator.all }),
  ])
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
  void invalidateAfterReaderProgress(client)
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
    client.invalidateQueries({ queryKey: queryKeys.readingPlans.all }),
    client.invalidateQueries({ queryKey: queryKeys.customCBLs.all }),
    client.invalidateQueries({ queryKey: queryKeys.roll.all }),
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
  await invalidateReadingEligibility(client)
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
  await client.invalidateQueries({
    queryKey: queryKeys.cblSources.readingListCandidates(saved.id),
    exact: true,
  })
  await invalidateReadingEligibility(client)
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
  await invalidateReadingEligibility(client)
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

/**
 * Apply updated preferences to the cache after a successful mutation.
 */
export function applyUpdatedPreferencesCache(
  client: QueryClient,
  preferences: { theme: 'classic' | 'ink-gold' | 'command-center'; user_id: number },
): void {
  client.setQueryData(queryKeys.preferences.detail(), preferences)
}

/**
 * Refresh the resources that carry `manual_die` after a die-mode change
 * (`POST /roll/set-die` or `POST /roll/clear-manual-die`).
 *
 * Pinned-versus-automatic mode is server truth, and both the roll bootstrap and
 * the current session report `manual_die`. Without this invalidation the cached
 * bootstrap keeps the pre-change value for the rest of the Roll session, so the
 * rating card can keep promising a ladder move that manual mode suppresses
 * (#3144) and the header's `Auto` segment keeps reading as selected.
 */
export async function invalidateAfterRollDieModeUpdate(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
  ])
}

/**
 * Invalidate the roll bootstrap and current session after a session-mode
 * update. Replaces the imperative `sessionApi.updateMode` + `refetchBootstrap()`
 * pattern in RollPage (#2649).
 *
 * A session-mode change and a die-mode change project the same retained
 * resources, so both share one invalidation implementation.
 */
export async function invalidateAfterSessionModeUpdate(
  client: QueryClient,
): Promise<void> {
  await invalidateAfterRollDieModeUpdate(client)
}

/**
 * Mark the roll bootstrap query stale when navigating away from Roll
 * (e.g., Roll -> Queue). This avoids an eager HTTP request on navigation
 * while preserving the #3761 pending-roll correctness guarantee: the query
 * will refetch on the next active use (returning to Roll) instead of
 * replaying a stale snapshot with `pending_thread_id: null`.
 */
export async function invalidateRollBootstrapOnNavigation(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
    refetchType: 'none',
  })
}

/**
 * Refresh every surface a tag mutation rewrites (issue #3032).
 *
 * Tag creates/updates/deletes and (bulk) assignment changes rewrite the tag
 * list, usage counts, and the effective tags of every touched target. The
 * Roll screen renders the rolled issue's effective tags inline, so the roll
 * bootstrap joins the refresh; the bootstrap refetch is what re-renders Roll
 * without navigating away. Other entity caches (queue pages, thread detail)
 * do not embed tags and stay untouched.
 *
 * TanStack Query refetches invalidated active queries — callers must not also
 * call `refetch()` for a key this helper already refreshes.
 */
export async function invalidateAfterTagMutation(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.tags.all }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
  ])
}

/** A global read can release requirements in other series and overlapping lists. */
async function invalidateReadingEligibility(client: QueryClient, includeAuthoringLists = false): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.thread.all }),
    client.invalidateQueries({ queryKey: queryKeys.queue.all }),
    client.invalidateQueries({ queryKey: queryKeys.roll.all }),
    client.invalidateQueries({ queryKey: queryKeys.dependencies.all }),
    client.invalidateQueries({ queryKey: queryKeys.readingPlans.all }),
    client.invalidateQueries({ queryKey: includeAuthoringLists ? queryKeys.customCBLs.all : queryKeys.customCBLs.readers() }),
    client.invalidateQueries({ queryKey: queryKeys.session.all }),
  ])
}

/** Refresh global read state without refetching a just-saved authoring draft. */
export async function invalidateAfterReaderProgress(client: QueryClient): Promise<void> {
  await invalidateReadingEligibility(client, true)
}
