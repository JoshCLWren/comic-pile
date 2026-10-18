import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { invalidateAfterCreatorCreditChange } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

function createSpiedClient() {
  const client = new QueryClient()
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()

  return { client, invalidateQueries }
}

describe('invalidateAfterCreatorCreditChange', () => {
  // #3461: creator analytics are derived server-side from a series' manual
  // creator credits, so an add/edit/remove must invalidate every creator
  // query prefix or the Creators pages keep serving the pre-edit cache.
  it('invalidates both creator query prefixes', async () => {
    const { client, invalidateQueries } = createSpiedClient()

    await invalidateAfterCreatorCreditChange(client)

    expect(invalidateQueries).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.creators.all })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.creator.all })
    expect(queryKeys.creators.all).toEqual(['creators'])
    expect(queryKeys.creator.all).toEqual(['creator'])
  })
})
