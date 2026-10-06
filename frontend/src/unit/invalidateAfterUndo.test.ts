import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { invalidateAfterUndo } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

function createSpiedClient() {
  const client = new QueryClient()
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()

  return { client, invalidateQueries }
}

describe('invalidateAfterUndo', () => {
  // #3194: after an undo the Roll page kept the stale pre-undo die size,
  // ready-to-read count, and rated issue until a manual browser reload.
  it('refreshes roll, session, queue, and snapshot caches after an undo', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateAfterUndo(client, 12)

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.queue.pages() })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.session.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.undo.all })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.detail(12),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.undo.snapshots(12),
    })
  })

  it('refreshes shared caches even without a session id', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateAfterUndo(client)

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.undo.all })
  })
})
