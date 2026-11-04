import { beforeEach, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateRollBootstrapOnNavigation } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const queryClient = new QueryClient()

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
})

it('invalidates roll bootstrap query without refetching on navigation', async () => {
  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
    refetchType: 'none',
  })
})

it('marks the query stale but does not trigger immediate refetch', async () => {
  // The helper uses refetchType: 'none' to avoid an eager HTTP request on
  // navigation, preserving the pending-roll correctness guarantee (#3761).
  // The query will refetch on the next active use (returning to Roll) instead
  // of replaying a stale snapshot with pending_thread_id: null.
  vi.mocked(queryClient.invalidateQueries).mockImplementation(async (options) => {
    if (options?.refetchType !== 'none') {
      throw new Error('Refetch should not be triggered')
    }
  })

  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1)
})
