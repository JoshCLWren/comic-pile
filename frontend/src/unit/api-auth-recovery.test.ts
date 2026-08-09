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

it('does not clear the access token when a suppressed refresh endpoint returns 401', async () => {
  setAccessToken('keep-me')
  const refreshError = {
    config: { url: '/v1/auth/refresh', skipAuthRedirect: true },
    response: { status: 401 },
  }

  await expect(responseInterceptor(refreshError)).rejects.toBe(refreshError)
  expect(getAccessToken()).toBe('keep-me')
})
