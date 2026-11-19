import { describe, expect, it, vi } from 'vitest'
import type { QueryClient } from '@tanstack/react-query'
import { invalidateReadingPlanReader } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

describe('invalidateReadingPlanReader', () => {
  it('invalidates the requested reading plan reader query', async () => {
    const invalidateQueries = vi.fn(async () => undefined)
    const client = { invalidateQueries } as unknown as QueryClient

    await invalidateReadingPlanReader(client, 42)

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.readingPlans.reader(42),
    })
  })
})
