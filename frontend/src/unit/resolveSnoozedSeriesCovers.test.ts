import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { queryKeys } from '../query/queryKeys'
import { resolveSnoozedSeriesCovers } from '../pages/RollPage/resolveSnoozedSeriesCovers'
import type { ThreadListItem } from '../types'

function thread(id: number, cover: string | null): ThreadListItem {
  return {
    id,
    title: `Series ${id}`,
    format: 'Comic',
    issues_remaining: 1,
    total_issues: 5,
    next_unread_issue_number: '3',
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2026-11-19T00:00:00Z',
    comicvine_mapping: null,
    series_cover_image_url: cover,
  }
}

function listApi(threads: ThreadListItem[] = []) {
  return { list: vi.fn().mockResolvedValue({ threads, next_page_token: null }) }
}

describe('Roll snoozed series cover resolution', () => {
  it('does not make any request for an empty shelf', async () => {
    const client = new QueryClient()
    const api = listApi()
    expect(await resolveSnoozedSeriesCovers([], client, api)).toEqual({})
    expect(api.list).not.toHaveBeenCalled()
  })

  it('reuses fresh planner series and does not issue a redundant network request', async () => {
    const client = new QueryClient()
    const api = listApi()
    client.setQueryData(queryKeys.thread.list(), [thread(7, 'https://example.test/plan.jpg')])
    expect(await resolveSnoozedSeriesCovers([{ id: 7 }], client, api)).toEqual({
      7: 'https://example.test/plan.jpg',
    })
    expect(api.list).not.toHaveBeenCalled()
  })

  it('prefers a newer cached Queue cover over an earlier planner projection', async () => {
    const client = new QueryClient()
    const api = listApi()
    const now = Date.now()
    client.setQueryData(queryKeys.thread.list(), [thread(7, 'https://example.test/old.jpg')], {
      updatedAt: now - 10_000,
    })
    client.setQueryData(queryKeys.queue.list({ sort: 'position', pageSize: 100 }), {
      pages: [{ threads: [thread(7, 'https://example.test/new.jpg')] }],
      pageParams: [null],
    }, { updatedAt: now - 500 })
    expect(await resolveSnoozedSeriesCovers([{ id: 7 }], client, api)).toEqual({
      7: 'https://example.test/new.jpg',
    })
    expect(api.list).not.toHaveBeenCalled()
  })

  it('rejects invalidated sources and uses just one first-page lookup for unresolved rows', async () => {
    const client = new QueryClient()
    const api = listApi([thread(8, 'https://example.test/fresh.jpg')])
    client.setQueryData(queryKeys.thread.list(), [thread(8, 'https://example.test/removed.jpg')])
    await client.invalidateQueries({ queryKey: queryKeys.thread.list() })
    const result = await resolveSnoozedSeriesCovers([{ id: 8 }, { id: 900 }], client, api)
    expect(result).toEqual({ 8: 'https://example.test/fresh.jpg' })
    expect(api.list).toHaveBeenCalledExactlyOnceWith({ page_size: 200 })
  })

  it('ignores expired cache data and keeps a shared placeholder when no cover exists', async () => {
    const client = new QueryClient()
    const api = listApi([thread(9, null)])
    client.setQueryData(queryKeys.thread.list(), [thread(9, 'https://example.test/stale.jpg')], {
      updatedAt: Date.now() - 120_000,
    })
    expect(await resolveSnoozedSeriesCovers([{ id: 9 }], client, api)).toEqual({ 9: null })
    expect(api.list).toHaveBeenCalledTimes(1)
  })

  it('reuses multi-page Queue cache without a sequential HTTP waterfall', async () => {
    const client = new QueryClient()
    const api = listApi()
    client.setQueryData(queryKeys.queue.list({ sort: 'position', pageSize: 100 }), {
      pages: [
        { threads: [thread(1, 'https://example.test/first.jpg')] },
        { threads: [thread(90, 'https://example.test/later.jpg')] },
      ],
      pageParams: [null, 'next'],
    })
    expect(await resolveSnoozedSeriesCovers([{ id: 90 }], client, api)).toEqual({
      90: 'https://example.test/later.jpg',
    })
    expect(api.list).not.toHaveBeenCalled()
  })
})
