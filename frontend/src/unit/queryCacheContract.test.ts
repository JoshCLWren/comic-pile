import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  applyEditedThreadToQueuePages,
  applyIssueCardMutation,
  applyRatedThreadCache,
  applyUpdatedThreadCache,
  invalidateAfterIssueEdit,
  invalidateAfterIssueMappingChange,
  invalidateAfterQueueMovement,
  invalidateAfterResumeRecovery,
  invalidateAfterThreadMetadataEdit,
  invalidateAfterUndo,
  invalidateCurrentSessionAfterSnooze,
  applyCreatedCustomCBL,
  applyUpdatedCustomCBL,
  applyDeletedCustomCBL,
  applyCommittedReadingPlan,
  invalidateSessionRecoveryCache,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import type { RateResponsePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { CustomCBL } from '../services/api-custom-cbl'
import type { ContinuityPlan } from '../services/api-continuity-plans'

const thread: Thread = {
  id: 7,
  title: 'Mister Miracle',
  format: 'issue',
  issues_remaining: 4,
  total_issues: 12,
  queue_position: 3,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2026-08-03T00:00:00Z',
}

function createSpiedClient() {
  const client = new QueryClient()
  const setQueryData = vi.spyOn(client, 'setQueryData')
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  const removeQueries = vi.spyOn(client, 'removeQueries').mockResolvedValue()
  const resetQueries = vi.spyOn(client, 'resetQueries').mockResolvedValue()

  return { client, setQueryData, invalidateQueries, removeQueries, resetQueries }
}

describe('canonical query keys', () => {
  it('represents every retained resource dimension without a Collections family', () => {
    expect(queryKeys).not.toHaveProperty('collections')

    expect(queryKeys.session.all).toEqual(['session'])
    expect(queryKeys.session.current()).toEqual(['session', 'current'])
    expect(queryKeys.session.pages()).toEqual(['session', 'pages'])
    expect(queryKeys.session.list()).toEqual(['session', 'pages', {}])
    expect(queryKeys.session.list({ params: { status: 'done' } })).toEqual([
      'session',
      'pages',
      { status: 'done' },
    ])
    expect(queryKeys.session.page({ pageSize: 20 })).toEqual([
      'session',
      'pages',
      { pageToken: null, pageSize: 20 },
    ])
    expect(queryKeys.session.page({ pageToken: 'next', pageSize: 10 })).toEqual([
      'session',
      'pages',
      { pageToken: 'next', pageSize: 10 },
    ])
    expect(queryKeys.session.detail(9)).toEqual(['session', 'detail', 9])

    expect(queryKeys.queue.all).toEqual(['queue'])
    expect(queryKeys.queue.pages()).toEqual(['queue', 'pages'])
    expect(
      queryKeys.queue.page({
        search: '   ',
        sort: 'position',
        pageSize: 25,
      }),
    ).toEqual([
      'queue',
      'pages',
      { search: null, sort: 'position', pageToken: null, pageSize: 25 },
    ])
    expect(
      queryKeys.queue.page({
        search: '  Batman  ',
        sort: 'alphabetical',
        pageToken: 'page-2',
        pageSize: 50,
      }),
    ).toEqual([
      'queue',
      'pages',
      {
        search: 'Batman',
        sort: 'alphabetical',
        pageToken: 'page-2',
        pageSize: 50,
      },
    ])

    expect(queryKeys.roll.all).toEqual(['roll'])
    expect(queryKeys.roll.bootstrap()).toEqual(['roll', 'bootstrap'])

    expect(queryKeys.completed.all).toEqual(['completed'])
    expect(queryKeys.completed.pages()).toEqual(['completed', 'pages'])
    expect(
      queryKeys.completed.list({ sort: 'created', pageSize: 25 }),
    ).toEqual(['completed', 'pages', { search: null, sort: 'created', pageSize: 25 }])
    expect(
      queryKeys.completed.page({
        search: '   ',
        sort: 'created',
        pageSize: 25,
      }),
    ).toEqual([
      'completed',
      'pages',
      { search: null, sort: 'created', pageToken: null, pageSize: 25 },
    ])
    expect(
      queryKeys.completed.page({
        search: '  Saga  ',
        sort: 'created',
        pageToken: 'page-2',
        pageSize: 50,
      }),
    ).toEqual([
      'completed',
      'pages',
      {
        search: 'Saga',
        sort: 'created',
        pageToken: 'page-2',
        pageSize: 50,
      },
    ])

    expect(queryKeys.thread.all).toEqual(['thread'])
    expect(queryKeys.thread.summaries()).toEqual(['thread', 'summary'])
    expect(queryKeys.thread.summary(7)).toEqual(['thread', 'summary', 7])
    expect(queryKeys.thread.details()).toEqual(['thread', 'detail'])
    expect(queryKeys.thread.detail(7)).toEqual(['thread', 'detail', 7])
    expect(queryKeys.thread.issuePages(7)).toEqual(['thread', 7, 'issues'])
    expect(queryKeys.thread.issuePage(7, { pageSize: 30 })).toEqual([
      'thread',
      7,
      'issues',
      { pageToken: null, pageSize: 30, status: null },
    ])
    expect(
      queryKeys.thread.issuePage(7, {
        pageToken: 'issues-2',
        pageSize: 15,
        status: 'unread',
      }),
    ).toEqual([
      'thread',
      7,
      'issues',
      { pageToken: 'issues-2', pageSize: 15, status: 'unread' },
    ])

    expect(queryKeys.dependencies.all).toEqual(['dependencies'])
    expect(queryKeys.dependencies.forThread(7)).toEqual([
      'dependencies',
      'thread',
      7,
    ])
    expect(queryKeys.dependencies.blocking(7)).toEqual([
      'dependencies',
      'blocking',
      7,
    ])
  })

  it('normalizes session list params and keeps the cursor out of the key', () => {
    expect(
      queryKeys.session.list({ params: { status: '  done  ', page_token: 'cursor-2' } }),
    ).toEqual(['session', 'pages', { status: 'done' }])
    expect(queryKeys.session.list({ params: { status: 'done', page_token: 'cursor-2' } })).toEqual(
      queryKeys.session.list({ params: { status: 'done', page_token: 'cursor-9' } }),
    )
    expect(queryKeys.session.list({ params: { status: 'done', note: '  ' } })).toEqual([
      'session',
      'pages',
      { status: 'done' },
    ])
  })
})

describe('targeted cache effects', () => {
  it('keeps an edited finished series current in its separately cached pages', () => {
    const client = new QueryClient()
    const listKey = queryKeys.completed.list({ sort: 'created', pageSize: 50 })
    const completed = { ...thread, status: 'completed' as const }
    client.setQueryData(listKey, {
      pages: [{ threads: [completed], next_page_token: null, active_count: 0 }],
      pageParams: [null],
    })

    const edited = { ...completed, title: 'Mister Miracle: Renamed' }
    applyEditedThreadToQueuePages(client, edited)

    const cached = client.getQueryData<{ pages: Array<{ threads: Thread[] }> }>(listKey)
    expect(cached?.pages[0]?.threads[0]?.title).toBe('Mister Miracle: Renamed')
    expect(client.getQueryData(queryKeys.thread.detail(thread.id))).toEqual(edited)
  })

  it('uses an authoritative rating response and reconciles open views after progress changes', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await applyRatedThreadCache(client, thread)

    expect(setQueryData).toHaveBeenNthCalledWith(
      1,
      queryKeys.thread.detail(thread.id),
      expect.any(Function),
    )
    expect(setQueryData).toHaveBeenNthCalledWith(
      2,
      queryKeys.thread.summary(thread.id),
      expect.any(Function),
    )
    // Native v2 returns thread progress, not the full detail representation.
    // Rating may update progress but must never replace authoritative metadata
    // with synthetic adapter values (such as queue_position: 0).
    // SAFETY: The preceding spy assertions verify the detail-cache argument is
    // a function updater. The test calls it with a valid Thread fixture.
    const update = setQueryData.mock.calls[0]?.[1] as (current: Thread) => Thread
    const existing: Thread = {
      ...thread,
      queue_position: 27,
      format: 'Trade Paperback',
      created_at: '2025-01-01T00:00:00Z',
    }
    expect(update(existing)).toMatchObject({
      queue_position: 27,
      format: 'Trade Paperback',
      created_at: '2025-01-01T00:00:00Z',
      issues_remaining: thread.issues_remaining,
      last_rating: thread.last_rating,
    })

    // Exact-count guard: every invalidation below is intentional; an
    // accidental extra key (or a dropped one) must fail this test.
    expect(invalidateQueries).toHaveBeenCalledTimes(17)
    expect(invalidateQueries).not.toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    // Reader-progress reconciliation refreshes the Finished Series shelf for
    // direct reads that complete a series; rating keeps its own conditional
    // reset when it marks a series completed.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })
    // A rating writes a new "After rating" snapshot (#3468), so both the Roll
    // undo list (`undo.all`) and the session view's snapshot list
    // (`session.snapshotsAll`) must stop serving the pre-rating list.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.undo.all })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.snapshotsAll(),
    })
    // The History card counts the same rows through the paginated session list.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.pages() })
    // Rating marks the issue read, so canonical reading boundaries must
    // recompute instead of retaining the pre-rating blocker.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.all })
    // Regression (#5264): open views must reconcile without a hard reload.
    // The paginated Queue is reset, never merely invalidated, so its loaded
    // pages cannot be refetched through stale cursors after a reorder (#933).
    expect(resetQueries).toHaveBeenCalledTimes(1)
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.all })
    expect(resetQueries).not.toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })
    expect(resetQueries).not.toHaveBeenCalledWith({ queryKey: queryKeys.excluded.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.eligibleIssueIdsAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.issueCardsAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.dieState(), exact: true })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.lastRead(), exact: true })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.bootstrap(), exact: true })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.activity.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.all })
  })

  it('can mark roll bootstrap stale without refetch when the caller owns the authoritative fetch (#5264)', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await applyRatedThreadCache(client, thread, { refetchRollBootstrap: false })

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
      refetchType: 'none',
    })
  })

  it('seeds the session last-read cache and the bootstrap projection from a committed rate', async () => {
    const { client } = createSpiedClient()
    const rated: RateResponsePayload = {
      ...thread,
      last_rating: 4,
      roll_reconciliation: {
        last_read: {
          issue_id: 31,
          issue_number: '5',
          read_at: '2026-08-03T18:30:00Z',
          thread_id: thread.id,
          thread_title: thread.title,
        },
      },
    }
    client.setQueryData<Partial<RollBootstrapResponse>>(queryKeys.roll.bootstrap(), {
      session_id: 12,
      last_read: null,
    })

    await applyRatedThreadCache(client, rated)

    expect(client.getQueryData(queryKeys.roll.lastRead())).toEqual(rated)
    expect(
      client.getQueryData<Partial<RollBootstrapResponse>>(queryKeys.roll.bootstrap())?.last_read,
    ).toEqual(rated.roll_reconciliation?.last_read)
  })

  it('does not clobber a newer last-read record when a rate lacks reconciliation data', async () => {
    const { client } = createSpiedClient()
    const existing: RateResponsePayload = {
      ...thread,
      last_rating: 3,
      roll_reconciliation: {
        last_read: {
          issue_id: 41,
          issue_number: '9',
          read_at: '2026-08-04T10:00:00Z',
          thread_id: thread.id,
          thread_title: thread.title,
        },
      },
    }
    client.setQueryData(queryKeys.roll.lastRead(), existing)

    await applyRatedThreadCache(client, thread)

    expect(client.getQueryData(queryKeys.roll.lastRead())).toEqual(existing)
  })

  it('updates a thread and narrowly refreshes queue, current session, and roll state', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await applyUpdatedThreadCache(client, thread)

    expect(setQueryData).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledTimes(5)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(resetQueries).not.toHaveBeenCalled()
  })

  it('invalidates completed pages when a direct read finishes a series issue (#5264)', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    const response = {
      die_after: null,
      final_rating: null,
      issue: {
        issue_id: 12,
        thread_id: thread.id,
        issue_number: '12',
        status: 'read',
        read_at: '2026-08-03T10:00:00Z',
        rating: null,
        has_confirmed_identity: false,
        mapping_state: 'none',
        comicvine_issue_id: null,
        cover_image_url: null,
        thread_title: thread.title,
      },
      rating_event_created: false,
      read_event_created: true,
      replayed: false,
      thread: {
        thread_id: thread.id,
        issues_remaining: 0,
        status: 'completed',
        last_rating: null,
        reading_progress: '12/12',
        next_unread_issue_id: null,
      },
    } satisfies Parameters<typeof applyIssueCardMutation>[1]

    await applyIssueCardMutation(client, response)

    // Direct reads go through the shared reader-progress reconciliation, so the
    // separately mounted Finished Series shelf must refresh without a reset.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })
    expect(resetQueries).not.toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })

    // Parent views that render the read label from their own query (rather than
    // from the shared card) must refresh too, or a saved read leaves crossover
    // progress and CBL preview labels stale (#4445).
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.crossover.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.cblSources.previewAll() })
  })

  it('invalidates edited issue surfaces and reconciles open views after read/progress edits', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterIssueEdit(client, thread.id)

    // Exact-count guard: issue pages/creators/detail/summary plus the shared
    // reader-progress pass; dropped keys or extra invalidations fail here.
    // Issue edits do not reorder the Queue, so they invalidate (not reset) it.
    expect(invalidateQueries).toHaveBeenCalledTimes(18)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.issuePages(thread.id),
    })
    // Issue mutations can change which issues carry confirmed provider
    // credits, so the bulk creator-credits map refreshes with the pages (#3461).
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.issueCreators(thread.id),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.detail(thread.id),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.summary(thread.id),
      exact: true,
    })
    // Regression (#5264): read/progress edits must reconcile Queue, Roll,
    // History/activity, and plan/list reader state across open views.
    // Only rating resets the Queue; issue edits keep isInvalidated semantics.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.eligibleIssueIdsAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.issueCardsAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.dieState(), exact: true })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.bootstrap(), exact: true })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.activity.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })
    // No shelf is reset unconditionally by a read/progress edit: the finished
    // shelf is only reset by mutation-specific callers on completion.
    expect(resetQueries).not.toHaveBeenCalled()
  })

  it('limits snooze reconciliation to the exact current session key', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateCurrentSessionAfterSnooze(client)

    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(resetQueries).not.toHaveBeenCalled()
  })

  it('limits queue movement refreshes to queue pages, the excluded shelf, current session, and roll state', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterQueueMovement(client)

    // Both membership lists reset: the active Queue and the excluded shelf a
    // series crosses into or out of (#3807).
    expect(resetQueries).toHaveBeenCalledTimes(2)
    expect(resetQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
    expect(resetQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.excluded.pages(),
    })
    expect(invalidateQueries).toHaveBeenCalledTimes(7)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.dieState(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    // The bounded whole-queue total must not survive a membership change (#3261).
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.activeCount(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.excluded.memberStatusAll(),
    })
  })

  it('skips only the session refresh when the owning mutation already refreshed it (#4276)', async () => {
    // The queue-row snooze/unsnooze mutation hooks refresh `session.current`
    // inside their own success path, so the row-action pass must not
    // re-invalidate that key: a second invalidation re-ran the session fetch
    // the mutation just settled. Every other movement surface still refreshes.
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterQueueMovement(client, { skipSessionCurrent: true })

    expect(resetQueries).toHaveBeenCalledTimes(2)
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.excluded.pages() })
    expect(invalidateQueries).toHaveBeenCalledTimes(6)
    expect(invalidateQueries).not.toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    // Roll state still goes stale so the next bootstrap mount refetches.
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.dieState(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.activeCount(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.excluded.memberStatusAll(),
    })
  })

  it('refreshes Roll, session, plan, and issue-card views after a thread rename without resetting queue pages (#5264)', async () => {
    const { client, invalidateQueries, resetQueries, setQueryData } = createSpiedClient()

    await invalidateAfterThreadMetadataEdit(client)

    expect(setQueryData).not.toHaveBeenCalled()
    expect(resetQueries).not.toHaveBeenCalled()
    expect(invalidateQueries).toHaveBeenCalledTimes(9)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.all })
    // #5486: the thread page Next-issue line reads these projections.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.readingBoundariesAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.blockingBatchAll() })
  })

  it('refreshes queue mapping counts and roll surfaces after a mapping change (#5264)', async () => {
    const { client, invalidateQueries, resetQueries, setQueryData } = createSpiedClient()

    await invalidateAfterIssueMappingChange(client)

    expect(setQueryData).not.toHaveBeenCalled()
    expect(resetQueries).not.toHaveBeenCalled()
    expect(invalidateQueries).toHaveBeenCalledTimes(5)
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
  })

  it('refreshes undo surfaces and reconciles open views while leaving session detail to its caller', async () => {
    const { client, invalidateQueries, resetQueries, setQueryData } = createSpiedClient()

    await invalidateAfterUndo(client)

    // Exact-count guards restored: two queue-movement resets and the full
    // invalidation set below. No extra key may creep into either pass.
    expect(resetQueries).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledTimes(16)
    // The queue half is composed from the queue-movement effect, not re-implemented.
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.excluded.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.dieState(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.activeCount(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.excluded.memberStatusAll(),
    })
    // The history card's "N issues read" total must stop counting an undone rating (#3194).
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.snapshotsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.undo.all })
    // Regression (#5264): undo restores read/blocker/history state across views.
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.activity.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.thread.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.all })

    // SAFETY: mock call args are typed as `unknown[]`; narrowing the first arg
    // to the optional queryKey shape the test then indexes is the checked invariant.
    const invalidatedKeys = invalidateQueries.mock.calls.map(
      (call) => (call[0] as { queryKey?: readonly unknown[] } | undefined)?.queryKey,
    )
    expect(invalidatedKeys.some((key) => key?.[0] === 'session' && key?.[1] === 'detail')).toBe(false)
    expect(invalidatedKeys.some((key) => key?.[0] === 'session' && key?.[1] === 'snapshots')).toBe(true)
    expect(invalidatedKeys).not.toContainEqual([...queryKeys.session.all])
    expect(setQueryData).not.toHaveBeenCalled()
  })

  it('reconciles retained and reader-progress surfaces on resume recovery', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterResumeRecovery(client)

    // Exact-count guards restored: scoped recovery set plus the reconciled
    // reader-progress surfaces; no unscoped invalidateQueries blast.
    expect(invalidateQueries).toHaveBeenCalledTimes(14)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.eligibleIssueIdsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.issueCardsAll(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.activeCount(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.snapshotsAll() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.activity.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.issueCards.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.thread.all })
    expect(setQueryData).not.toHaveBeenCalled()
    expect(resetQueries).toHaveBeenCalledTimes(2)
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.completed.pages() })
    expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.excluded.pages() })
  })

  describe('custom CBL cache effects', () => {
    const customCBL: CustomCBL = {
      id: 42,
      name: 'My Custom List',
      description: 'A test custom list',
      mode: 'loose',
      issue_count: 5,
      user_id: 1,
      created_at: '2026-08-03T00:00:00Z',
      updated_at: '2026-08-03T00:00:00Z',
      entries: [
        { id: 1, position: 0, issue_id: 100, thread_id: 7, series_name: 'Batman', issue_number: '#1', status: 'read', is_checkpoint: false, gate: 'none', skipped: false },
        { id: 2, position: 1, issue_id: 101, thread_id: 8, series_name: 'Superman', issue_number: '#1', status: 'unread', is_checkpoint: false, gate: 'none', skipped: false },
      ],
    }

    it('applies a created custom CBL to detail cache and invalidates list', async () => {
      const { client, setQueryData, invalidateQueries } = createSpiedClient()

      await applyCreatedCustomCBL(client, customCBL)

      expect(setQueryData).toHaveBeenCalledWith(queryKeys.customCBLs.detail(customCBL.id), customCBL)
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.list(), exact: true })
    })

    it('applies an updated custom CBL to detail cache and invalidates list', async () => {
      const { client, setQueryData, invalidateQueries } = createSpiedClient()

      await applyUpdatedCustomCBL(client, customCBL)

      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.readers() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.eligibleIssueIdsAll() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.issueCardsAll() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.dieState(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.bootstrap(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.dependencies.all })
      // Saving a list changes the confirmed identities its CBL candidates were
      // compared with, so the candidate query must not serve the stale match set.
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.cblSources.readingListCandidates(customCBL.id),
        exact: true,
      })

      expect(setQueryData).toHaveBeenCalledWith(queryKeys.customCBLs.detail(customCBL.id), customCBL)
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.list(), exact: true })
    })

    it('removes a deleted custom CBL from detail cache and invalidates list', async () => {
      const { client, removeQueries, invalidateQueries } = createSpiedClient()

      await applyDeletedCustomCBL(client, customCBL.id)

      expect(removeQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.detail(customCBL.id), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.customCBLs.list(), exact: true })
    })
  })

  describe('reading plan cache effects', () => {
    const readingPlan: ContinuityPlan = {
      id: 99,
      name: 'Test Reading Plan',
      ordering_mode: 'strict_sequential',
      created_at: '2026-08-03T00:00:00Z',
      updated_at: '2026-08-03T00:00:00Z',
      user_id: 1,
      lanes: [
        {
          id: 'test-lane',
          name: 'Test Lane',
          order: 0,
        },
      ],
      nodes: [],
    }

    it('applies a committed reading plan to detail cache and invalidates dependent queries', async () => {
      const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

      await applyCommittedReadingPlan(client, readingPlan)

      expect(setQueryData).toHaveBeenCalledWith(queryKeys.readingPlans.detail(readingPlan.id), readingPlan)
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.list(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.reader(readingPlan.id) })
      expect(resetQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.current(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.bootstrap(), exact: true })
    })
  })

  describe('session recovery cache effects', () => {
    it('invalidates all queries affected by session recovery', async () => {
      const { client, invalidateQueries } = createSpiedClient()

      await invalidateSessionRecoveryCache(client)

      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.current(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.bootstrap(), exact: true })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.eligibleIssueIdsAll() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.roll.issueCardsAll() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    })
  })
})
