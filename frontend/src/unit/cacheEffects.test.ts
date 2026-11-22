import { describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateReadingPlanReader } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

describe('invalidateReadingPlanReader', () => {
  it('invalidates the requested reading plan reader query', async () => {
    const client = new QueryClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()

    await invalidateReadingPlanReader(client, 42)

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.readingPlans.reader(42),
    })
  })
})
