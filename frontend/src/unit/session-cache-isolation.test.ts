import { QueryClient, isCancelledError } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { clearSessionCache } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

describe('session cache isolation', () => {
  it('cancels a previous account query even when its transport ignores cancellation', async () => {
    const client = new QueryClient()
    const key = queryKeys.preferences.detail()
    let finish!: (data: { user_id: number }) => void
    const pending = client.fetchQuery({
      queryKey: key,
      queryFn: () => new Promise<{ user_id: number }>(resolve => { finish = resolve }),
    }).catch(error => error)

    clearSessionCache(client)
    client.setQueryData(key, { user_id: 2 })
    finish({ user_id: 1 })

    expect(isCancelledError(await pending)).toBe(true)
    expect(client.getQueryData(key)).toEqual({ user_id: 2 })
  })
})
