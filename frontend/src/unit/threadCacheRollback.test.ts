import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { optimisticallyUpdateThreadCache } from '../query/cacheEffects'
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

describe('optimistic thread cache rollback', () => {
  it('updates detail and summary together and restores both snapshots', () => {
    const client = new QueryClient()
    const detailKey = queryKeys.thread.detail(thread.id)
    const summaryKey = queryKeys.thread.summary(thread.id)
    client.setQueryData(detailKey, thread)
    client.setQueryData(summaryKey, thread)

    const rollback = optimisticallyUpdateThreadCache(client, thread.id, (current) => ({
      ...current,
      title: 'Mister Miracle: The Source of Freedom',
    }))

    expect(client.getQueryData<Thread>(detailKey)?.title).toBe(
      'Mister Miracle: The Source of Freedom',
    )
    expect(client.getQueryData<Thread>(summaryKey)?.title).toBe(
      'Mister Miracle: The Source of Freedom',
    )

    rollback()

    expect(client.getQueryData(detailKey)).toEqual(thread)
    expect(client.getQueryData(summaryKey)).toEqual(thread)
  })

  it('does not manufacture missing cache entries and rollback keeps them absent', () => {
    const client = new QueryClient()
    const detailKey = queryKeys.thread.detail(thread.id)
    const summaryKey = queryKeys.thread.summary(thread.id)

    const rollback = optimisticallyUpdateThreadCache(client, thread.id, (current) => ({
      ...current,
      title: 'Unused optimistic title',
    }))

    expect(client.getQueryData(detailKey)).toBeUndefined()
    expect(client.getQueryData(summaryKey)).toBeUndefined()

    rollback()

    expect(client.getQueryData(detailKey)).toBeUndefined()
    expect(client.getQueryData(summaryKey)).toBeUndefined()
  })

  it('rolls back each cache entry to its own authoritative snapshot', () => {
    const client = new QueryClient()
    const detailKey = queryKeys.thread.detail(thread.id)
    const summaryKey = queryKeys.thread.summary(thread.id)
    const summary = { ...thread, title: 'Compact summary title' }
    client.setQueryData(detailKey, thread)
    client.setQueryData(summaryKey, summary)

    const rollback = optimisticallyUpdateThreadCache(client, thread.id, (current) => ({
      ...current,
      issues_remaining: current.issues_remaining - 1,
    }))

    expect(client.getQueryData<Thread>(detailKey)?.issues_remaining).toBe(3)
    expect(client.getQueryData<Thread>(summaryKey)?.issues_remaining).toBe(3)

    rollback()

    expect(client.getQueryData(detailKey)).toEqual(thread)
    expect(client.getQueryData(summaryKey)).toEqual(summary)
  })
})
