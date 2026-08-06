import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  request: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
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

import { clearAccessToken } from '../services/api'

const requestInterceptor = apiMock.interceptors.request.use.mock.calls[0][0] as (
  config: { method?: string; url?: string; headers?: Record<string, string> },
) => Promise<{ method?: string; url?: string; headers?: Record<string, string> }>

const responseInterceptor = apiMock.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string> }
    response: { status: number; data?: unknown }
  },
) => Promise<unknown>

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.request.mockReset()
  clearAccessToken()
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 1970 00:00:00 GMT; path=/'
})

it('bootstraps csrf through the canonical v1 auth endpoint', async () => {
  apiMock.get.mockResolvedValue({ csrf_token: 'fresh-token' })

  const config = await requestInterceptor({
    method: 'delete',
    url: '/threads/9',
    headers: {},
  })

  expect(apiMock.get).toHaveBeenCalledWith('/v1/auth/csrf', { skipAuthRedirect: true })
  expect(config.headers).toEqual({ 'X-CSRF-Token': 'fresh-token' })
})

it('keeps canonical credential endpoints exempt from csrf bootstrap', async () => {
  const login = await requestInterceptor({ method: 'post', url: '/v1/auth/login', headers: {} })
  const register = await requestInterceptor({ method: 'post', url: '/v1/auth/register', headers: {} })
  const refresh = await requestInterceptor({ method: 'post', url: '/v1/auth/refresh', headers: {} })

  expect(login.headers).toEqual({})
  expect(register.headers).toEqual({})
  expect(refresh.headers).toEqual({})
  expect(apiMock.get).not.toHaveBeenCalled()
})

it('refreshes expired requests through the canonical v1 auth endpoint', async () => {
  apiMock.post.mockResolvedValue({ access_token: 'refreshed-token' })
  apiMock.request.mockResolvedValue({ refreshed: true })

  const originalRequest = { url: '/v1/threads/42', headers: {} }
  const result = await responseInterceptor({
    config: originalRequest,
    response: { status: 401 },
  })

  expect(apiMock.post).toHaveBeenCalledWith('/v1/auth/refresh')
  expect(apiMock.request).toHaveBeenCalledWith({
    ...originalRequest,
    _retry: true,
    headers: { Authorization: 'Bearer refreshed-token' },
  })
  expect(result).toEqual({ refreshed: true })
})
