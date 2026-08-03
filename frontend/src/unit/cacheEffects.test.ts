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

  it('uses a thread edit response directly and recalculates only affected screens', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')
    const thread = buildThread(9)

    await applyUpdatedThreadCache(client, thread)

    expect(client.getQueryData(queryKeys.thread.detail(9))).toEqual(thread)
    expect(client.getQueryData(queryKeys.thread.summary(9))).toEqual(thread)
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
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.session.pages() }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.dependencies.all }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.analytics.all }),
    )
  })

  it('invalidates only the edited thread issue pages, summaries, detail, and current session', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')

    await invalidateAfterIssueEdit(client, 12)

    expect(invalidateQueries).toHaveBeenCalledTimes(4)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.issuePages(12),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.detail(12),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.thread.summary(12),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.thread.issuePages(13) }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.queue.pages() }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.roll.bootstrap() }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.dependencies.all }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.analytics.all }),
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

  it('invalidates queue pages and their selection owners without evicting unrelated resources', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')

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
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.thread.all }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.session.pages() }),
    )
    expect(invalidateQueries).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.analytics.all }),
    )
  })
})
