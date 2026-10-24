import { beforeEach, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateRollBootstrapOnNavigation } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const mockQueryClient = {
  invalidateQueries: vi.fn(),
} as unknown as QueryClient

beforeEach(() => {
  vi.clearAllMocks()
})

it('invalidates roll bootstrap query without refetching when called', async () => {
  await invalidateRollBootstrapOnNavigation(mockQueryClient)

  expect(mockQueryClient.invalidateQueries).toHaveBeenCalledWith({
    queryKey: queryKeys.roll.bootstrap(),
    exact: true,
    refetchType: 'none',
  })
})

it('does not trigger refetch of active queries', async () => {
  // Mock invalidateQueries to track if it would trigger refetch
  mockQueryClient.invalidateQueries = vi.fn().mockImplementation((options) => {
    // If refetchType is not 'none', it would trigger refetch
    if (options.refetchType !== 'none') {
      throw new Error('Refetch should not be triggered')
    }
  })

  await invalidateRollBootstrapOnNavigation(mockQueryClient)

  expect(mockQueryClient.invalidateQueries).toHaveBeenCalledTimes(1)
})