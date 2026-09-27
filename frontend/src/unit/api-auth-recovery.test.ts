import { beforeEach, expect, it } from 'vitest'
import { createApiClient, getAccessToken, setAccessToken } from '../services/api'
import { createTransportDouble } from './transportDouble'

const transport = createTransportDouble()
createApiClient(() => transport)


// SAFETY: transport.interceptors.response.use is a vi.fn(); first call's second arg is the response interceptor with expected signature.
const responseInterceptor = transport.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string>; skipAuthRedirect?: boolean }
    response: { status: number }
  },
) => Promise<Record<string, string | number | boolean | null>>

beforeEach(() => {
  transport.post.mockReset()
  transport.request.mockReset()
  setAccessToken(null)
})

it('propagates recovery redirect suppression into an internal token refresh', async () => {
  const refreshError = Object.assign(new Error('refresh unauthorized'), {
    response: { status: 401 },
  })
  transport.post.mockRejectedValueOnce(refreshError)

  await expect(responseInterceptor({
    config: { url: '/v1/auth/me', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toBe(refreshError)

  expect(transport.post).toHaveBeenCalledWith('/v1/auth/refresh', undefined, {
    skipAuthRedirect: true,
  })
})

it('clears a stale access token when refresh itself returns 401', async () => {
  setAccessToken('stale-access-token')
  const refreshError = {
    config: { url: '/v1/auth/refresh', skipAuthRedirect: true },
    response: { status: 401 },
  }

  await expect(responseInterceptor(refreshError)).rejects.toBe(refreshError)
  expect(getAccessToken()).toBeNull()
})

it('does not stampede refresh after a missing-cookie 401', async () => {
  setAccessToken('stale-access-token')
  const refreshError = Object.assign(new Error('refresh unauthorized'), {
    response: { status: 401 },
  })
  transport.post.mockRejectedValue(refreshError)

  await expect(responseInterceptor({
    config: { url: '/v1/auth/me', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toBe(refreshError)
  expect(getAccessToken()).toBeNull()
  expect(transport.post).toHaveBeenCalledTimes(1)

  await expect(responseInterceptor({
    config: { url: '/v1/threads/', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toMatchObject({ response: { status: 401 } })
  expect(transport.post).toHaveBeenCalledTimes(1)
})
