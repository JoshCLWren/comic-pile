import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  applyRatedThreadCache,
  applyUpdatedThreadCache,
  invalidateAfterIssueEdit,
  invalidateAfterQueueMovement,
  invalidateAfterResumeRecovery,
  invalidateCurrentSessionAfterSnooze,
  invalidateAfterSessionModeUpdate,
  applyCreatedCustomCBL,
  applyUpdatedCustomCBL,
  applyDeletedCustomCBL,
  applyCommittedReadingPlan,
  invalidateSessionRecoveryCache,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import type { Thread } from '../types'
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
    expect(queryKeys.analytics.all).toEqual(['analytics'])
    expect(queryKeys.analytics.overview()).toEqual(['analytics', 'overview'])
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
  it('uses an authoritative rating response and invalidates only current session', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await applyRatedThreadCache(client, thread)

    expect(setQueryData).toHaveBeenNthCalledWith(
      1,
      queryKeys.thread.detail(thread.id),
      thread,
    )
    expect(setQueryData).toHaveBeenNthCalledWith(
      2,
      queryKeys.thread.summary(thread.id),
      thread,
    )
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(resetQueries).not.toHaveBeenCalled()
  })

  it('updates a thread and narrowly refreshes queue, current session, and roll state', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await applyUpdatedThreadCache(client, thread)

    expect(setQueryData).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledTimes(3)
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
    expect(resetQueries).not.toHaveBeenCalled()
  })

  it('invalidates the edited thread issue, detail, summary, session, and queue keys', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterIssueEdit(client, thread.id)

    expect(invalidateQueries).toHaveBeenCalledTimes(5)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.issuePages(thread.id),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.detail(thread.id),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.summary(thread.id),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
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

  it('limits queue movement refreshes to queue pages, current session, and roll state', async () => {
    const { client, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterQueueMovement(client)

    expect(resetQueries).toHaveBeenCalledTimes(1)
    expect(resetQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
    expect(invalidateQueries).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
  })

  it('limits resume recovery to the scoped resume set without an unscoped invalidate', async () => {
    const { client, setQueryData, invalidateQueries, resetQueries } = createSpiedClient()

    await invalidateAfterResumeRecovery(client)

    expect(invalidateQueries).toHaveBeenCalledTimes(3)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.queue.pages(),
    })
    expect(setQueryData).not.toHaveBeenCalled()
    expect(resetQueries).not.toHaveBeenCalled()
  })

  describe('custom CBL cache effects', () => {
    const customCBL: CustomCBL = {
      id: 42,
      name: 'My Custom List',
      description: 'A test custom list',
      issue_count: 5,
      user_id: 1,
      created_at: '2026-08-03T00:00:00Z',
      updated_at: '2026-08-03T00:00:00Z',
      entries: [
        { id: 1, position: 0, issue_id: 100, thread_id: 7, series_name: 'Batman', issue_number: '#1', status: 'read' },
        { id: 2, position: 1, issue_id: 101, thread_id: 8, series_name: 'Superman', issue_number: '#1', status: 'unread' },
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
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.readingPlans.all })
    })
  })

  describe('session mode cache effects', () => {
    it('invalidates roll bootstrap and current session after a session-mode update', async () => {
      const { client, invalidateQueries, resetQueries } = createSpiedClient()

      await invalidateAfterSessionModeUpdate(client)

      expect(invalidateQueries).toHaveBeenCalledTimes(2)
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.roll.bootstrap(),
        exact: true,
      })
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.session.current(),
        exact: true,
      })
      expect(resetQueries).not.toHaveBeenCalled()
    })
  })
})
