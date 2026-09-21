import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { invalidateAfterSessionModeUpdate } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

function createSpiedClient() {
  const client = new QueryClient()
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  const resetQueries = vi.spyOn(client, 'resetQueries').mockResolvedValue()

  return { client, invalidateQueries, resetQueries }
}

describe('invalidateAfterSessionModeUpdate', () => {
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
