import { beforeEach, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateRollBootstrapOnNavigation } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const queryClient = new QueryClient()

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
})

it('invalidates roll bootstrap query and refetches when called', async () => {
  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
    refetchType: 'all',
  })
})

it('triggers a refetch of active queries', async () => {
  // The helper refetches on navigation so the cached die state stays consistent
  // with the server after a manual-die change (#4279).
  vi.mocked(queryClient.invalidateQueries).mockImplementation(async (options) => {
    if (options?.refetchType !== 'all') {
      throw new Error('Refetch should be triggered')
    }
  })

  await invalidateRollBootstrapOnNavigation(queryClient)

  expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1)
})
