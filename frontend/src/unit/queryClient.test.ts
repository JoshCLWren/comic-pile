import { describe, expect, it } from 'vitest'
import { queryClient } from '../query/queryClient'

function responseError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: {
      status,
      data: detail === undefined ? undefined : { detail },
    },
  })
}

describe('queryClient defaults', () => {
  it('configures cache and mutation behavior', () => {
    const defaults = queryClient.getDefaultOptions()

    expect(defaults.queries?.staleTime).toBe(30_000)
    expect(defaults.queries?.gcTime).toBe(5 * 60_000)
    expect(defaults.queries?.refetchOnWindowFocus).toBe(false)
    expect(defaults.mutations?.retry).toBe(false)
  })

  it('suppresses auth retries and bounds transient retries', () => {
    const retry = queryClient.getDefaultOptions().queries?.retry
    expect(typeof retry).toBe('function')
    if (typeof retry !== 'function') {
      throw new Error('Expected query retry policy to be a function')
    }

    expect(retry(0, responseError(401))).toBe(false)
    expect(retry(0, responseError(403, 'Not authenticated'))).toBe(false)
    expect(retry(0, responseError(403, 'Forbidden'))).toBe(true)
    expect(retry(2, new Error('temporary'))).toBe(true)
    expect(retry(3, new Error('temporary'))).toBe(false)
  })
})
