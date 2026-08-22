import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  applyRatedThreadCache,
  applyUpdatedThreadCache,
  invalidateAfterIssueEdit,
  invalidateAfterQueueMovement,
  invalidateCurrentSessionAfterSnooze,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import type { Thread } from '../types'

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

  return { client, setQueryData, invalidateQueries }
}

describe('canonical query keys', () => {
  it('represents every retained resource dimension without a Collections family', () => {
    expect(queryKeys).not.toHaveProperty('collections')

    expect(queryKeys.session.all).toEqual(['session'])
    expect(queryKeys.session.current()).toEqual(['session', 'current'])
    expect(queryKeys.session.pages()).toEqual(['session', 'pages'])
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
})

describe('targeted cache effects', () => {
  it('uses an authoritative rating response and invalidates only current session', async () => {
    const { client, setQueryData, invalidateQueries } = createSpiedClient()

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
  })

  it('updates a thread and narrowly refreshes queue, current session, and roll state', async () => {
    const { client, setQueryData, invalidateQueries } = createSpiedClient()

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
  })

  it('invalidates only the edited thread issue, detail, summary, and session keys', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateAfterIssueEdit(client, thread.id)

    expect(invalidateQueries).toHaveBeenCalledTimes(4)
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
  })

  it('limits snooze reconciliation to the exact current session key', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateCurrentSessionAfterSnooze(client)

    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
  })

  it('limits queue movement refreshes to queue pages, current session, and roll state', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateAfterQueueMovement(client)

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
  })
})
