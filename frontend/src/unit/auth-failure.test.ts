import axios from 'axios'
import { describe, expect, it } from 'vitest'
import { isDefinitiveAuthenticationFailure } from '../services/authFailure'

function axiosError(status?: number) {
  return new axios.AxiosError(
    'request failed',
    undefined,
    undefined,
    undefined,
    status === undefined
      ? undefined
      : {
          status,
          statusText: 'Error',
          headers: {},
          config: { headers: new axios.AxiosHeaders() },
          data: { detail: 'temporary failure' },
        },
  )
}

describe('isDefinitiveAuthenticationFailure', () => {
  it('treats a 401 as definitive authentication loss', () => {
    expect(isDefinitiveAuthenticationFailure(axiosError(401))).toBe(true)
  })

  it.each([403, 408, 429, 500, 502, 503, 504])(
    'keeps status %s recoverable until persistent credentials are rejected',
    (status) => {
      expect(isDefinitiveAuthenticationFailure(axiosError(status))).toBe(false)
    },
  )

  it('keeps network and timeout failures recoverable', () => {
    expect(isDefinitiveAuthenticationFailure(axiosError())).toBe(false)
    expect(isDefinitiveAuthenticationFailure(new Error('network timeout'))).toBe(false)
  })
})
