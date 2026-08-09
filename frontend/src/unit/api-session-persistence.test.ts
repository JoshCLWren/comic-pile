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

import { clearAccessToken, getAccessToken, setAccessToken } from '../services/api'

const responseInterceptor = apiMock.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string> }
    response: { status: number; data?: unknown }
  },
) => Promise<unknown>

beforeEach(() => {
  apiMock.post.mockReset()
  apiMock.request.mockReset()
  clearAccessToken()
})

it.each([
  ['a cold-start server error', Object.assign(new Error('service unavailable'), { response: { status: 503 } })],
  ['a temporary network failure', new Error('network timeout')],
])('keeps the current session after %s during token refresh', async (_description, refreshError) => {
  setAccessToken('preserve-this-token')
  apiMock.post.mockRejectedValueOnce(refreshError)

  await expect(
    responseInterceptor({
      config: { url: '/v1/auth/me', headers: {} },
      response: { status: 401 },
    }),
  ).rejects.toBe(refreshError)

  expect(getAccessToken()).toBe('preserve-this-token')
  expect(apiMock.request).not.toHaveBeenCalled()
})
