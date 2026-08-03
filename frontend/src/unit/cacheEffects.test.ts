import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  applyRatedThreadCache,
  invalidateCurrentSessionAfterSnooze,
} from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import type { Thread } from '../types'

function buildThread(id: number): Thread {
  return {
    id,
    title: 'Saga',
  } as Thread
}

describe('retained mutation cache effects', () => {
  it('uses the rating response as authoritative thread state and invalidates current session only', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')
    const thread = buildThread(7)

    await applyRatedThreadCache(client, thread)

    expect(client.getQueryData(queryKeys.thread.detail(7))).toEqual(thread)
    expect(client.getQueryData(queryKeys.thread.summary(7))).toEqual(thread)
    expect(invalidateQueries).toHaveBeenCalledTimes(1)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.queue.pages() }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.thread.all }),
    )
  })

  it('reconciles snooze and unsnooze through current-session state without thread-page invalidation', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')

    await invalidateCurrentSessionAfterSnooze(client)

    expect(invalidateQueries).toHaveBeenCalledTimes(1)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.thread.all }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.analytics.all }),
    )
  })
})
