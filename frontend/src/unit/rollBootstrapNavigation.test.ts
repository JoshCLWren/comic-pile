import { beforeEach, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateRollBootstrapOnNavigation } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const queryClient = new QueryClient()

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
})

it('invalidates roll bootstrap query without refetching when called', async () => {
  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
    refetchType: 'none',
  })
})

it('does not trigger refetch of active queries', async () => {
  // If refetchType is not 'none', the helper would trigger an eager fetch.
  vi.mocked(queryClient.invalidateQueries).mockImplementation(async (options) => {
    if (options?.refetchType !== 'none') {
      throw new Error('Refetch should not be triggered')
    }
  })

  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1)
})
