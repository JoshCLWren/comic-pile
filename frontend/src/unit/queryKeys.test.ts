import { describe, expect, it } from 'vitest'
import { queryKeys } from '../query/queryKeys'

describe('queryKeys', () => {
  it('builds stable session keys with pagination inputs', () => {
    expect(queryKeys.session.all).toEqual(['session'])
    expect(queryKeys.session.current()).toEqual(['session', 'current'])
    expect(queryKeys.session.pages()).toEqual(['session', 'pages'])
    expect(queryKeys.session.page({ pageSize: 25 })).toEqual([
      'session',
      'pages',
      { pageToken: null, pageSize: 25 },
    ])
    expect(queryKeys.session.page({ pageToken: 'sessions-2', pageSize: 10 })).toEqual([
      'session',
      'pages',
      { pageToken: 'sessions-2', pageSize: 10 },
    ])
    expect(queryKeys.session.detail(42)).toEqual(['session', 'detail', 42])
  })

  it('normalizes queue search and includes every page-shaping input', () => {
    expect(queryKeys.queue.all).toEqual(['queue'])
    expect(queryKeys.queue.pages()).toEqual(['queue', 'pages'])
    expect(
      queryKeys.queue.page({
        search: '  Saga  ',
        sort: 'alphabetical',
        pageToken: 'next-1',
        pageSize: 50,
      }),
    ).toEqual([
      'queue',
      'pages',
      {
        search: 'Saga',
        sort: 'alphabetical',
        pageToken: 'next-1',
        pageSize: 50,
      },
    ])

    expect(
      queryKeys.queue.page({
        search: '   ',
        sort: 'position',
        pageSize: 20,
      }),
    ).toEqual([
      'queue',
      'pages',
      {
        search: null,
        sort: 'position',
        pageToken: null,
        pageSize: 20,
      },
    ])
  })

  it('scopes every thread and dependency key by resource id', () => {
    expect(queryKeys.thread.all).toEqual(['thread'])
    expect(queryKeys.thread.summaries()).toEqual(['thread', 'summary'])
    expect(queryKeys.thread.summary(7)).toEqual(['thread', 'summary', 7])
    expect(queryKeys.thread.details()).toEqual(['thread', 'detail'])
    expect(queryKeys.thread.detail(7)).toEqual(['thread', 'detail', 7])
    expect(queryKeys.thread.issuePages(7)).toEqual(['thread', 7, 'issues'])
    expect(
      queryKeys.thread.issuePage(7, {
        pageToken: 'issues-2',
        pageSize: 100,
        status: 'unread',
      }),
    ).toEqual([
      'thread',
      7,
      'issues',
      {
        pageToken: 'issues-2',
        pageSize: 100,
        status: 'unread',
      },
    ])
    expect(queryKeys.thread.issuePage(7, { pageSize: 25 })).toEqual([
      'thread',
      7,
      'issues',
      {
        pageToken: null,
        pageSize: 25,
        status: null,
      },
    ])
    expect(queryKeys.dependencies.all).toEqual(['dependencies'])
    expect(queryKeys.dependencies.forThread(7)).toEqual(['dependencies', 'thread', 7])
    expect(queryKeys.dependencies.blocking(7)).toEqual(['dependencies', 'blocking', 7])
  })

  it('defines retained roll and analytics roots without a collections key family', () => {
    expect(queryKeys.roll.all).toEqual(['roll'])
    expect(queryKeys.roll.bootstrap()).toEqual(['roll', 'bootstrap'])
    expect(queryKeys.analytics.all).toEqual(['analytics'])
    expect(queryKeys.analytics.overview()).toEqual(['analytics', 'overview'])
    expect('collections' in queryKeys).toBe(false)
  })
})
