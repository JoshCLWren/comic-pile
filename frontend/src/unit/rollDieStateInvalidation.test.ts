import { beforeEach, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateAfterRollDieModeUpdate } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const queryClient = new QueryClient()

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
})

it('refreshes the scoped die-state resource after a die command (#4719)', async () => {
  await invalidateAfterRollDieModeUpdate(queryClient)

  // The Roll header reads its selected die from the scoped resource. Without
  // this invalidation, set-die/roll/reset leaves the header on the replaced die
  // until the query's stale window elapses.
  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.dieState(),
    exact: true,
  })
})

it('keeps refreshing bootstrap and the current session with the scoped die', async () => {
  await invalidateAfterRollDieModeUpdate(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
  })
  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
})
