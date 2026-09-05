import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  request: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { getAccessToken, setAccessToken } from '../services/api'

const responseInterceptor = apiMock.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string>; skipAuthRedirect?: boolean }
    response: { status: number }
  },
) => Promise<unknown>

beforeEach(() => {
  apiMock.post.mockReset()
  apiMock.request.mockReset()
  setAccessToken(null)
})

it('propagates recovery redirect suppression into an internal token refresh', async () => {
  const refreshError = Object.assign(new Error('refresh unauthorized'), {
    response: { status: 401 },
  })
  apiMock.post.mockRejectedValueOnce(refreshError)

  await expect(responseInterceptor({
    config: { url: '/v1/auth/me', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toBe(refreshError)

  expect(apiMock.post).toHaveBeenCalledWith('/v1/auth/refresh', undefined, {
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
  apiMock.post.mockRejectedValue(refreshError)

  await expect(responseInterceptor({
    config: { url: '/v1/auth/me', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toBe(refreshError)
  expect(getAccessToken()).toBeNull()
  expect(apiMock.post).toHaveBeenCalledTimes(1)

  await expect(responseInterceptor({
    config: { url: '/v1/threads/', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toMatchObject({ response: { status: 401 } })
  expect(apiMock.post).toHaveBeenCalledTimes(1)
})
