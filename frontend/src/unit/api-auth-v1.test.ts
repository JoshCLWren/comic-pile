import { beforeEach, expect, it, vi } from 'vitest'
import { createApiClient, setAccessToken } from '../services/api'
import { createTransportDouble } from './transportDouble'

const transport = createTransportDouble()
createApiClient(() => transport)


// SAFETY: transport.interceptors.request.use is a vi.fn(); first call's first arg is the request interceptor with expected signature.
const requestInterceptor = transport.interceptors.request.use.mock.calls[0][0] as (
  config: { method?: string; url?: string; headers?: Record<string, string> },
) => Promise<{ method?: string; url?: string; headers?: Record<string, string> }>

// SAFETY: transport.interceptors.response.use is a vi.fn(); first call's second arg is the response interceptor with expected signature.
const responseInterceptor = transport.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string>; data?: unknown }
    response: { status: number; data?: unknown }
    name?: string
    message?: string
  },
) => Promise<Record<string, string | number | boolean | null>>

beforeEach(() => {
  transport.get.mockReset()
  transport.post.mockReset()
  transport.request.mockReset()
  setAccessToken(null)
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

it('bootstraps csrf through the canonical v1 auth endpoint', async () => {
  transport.get.mockResolvedValue({ csrf_token: 'fresh-token' })

  const config = await requestInterceptor({
    method: 'delete',
    url: '/threads/9',
    headers: {},
  })

  expect(transport.get).toHaveBeenCalledWith('/v1/auth/csrf', { skipAuthRedirect: true })
  expect(config.headers).toEqual({ 'X-CSRF-Token': 'fresh-token' })
})

it('keeps canonical credential endpoints exempt from csrf bootstrap', async () => {
  const login = await requestInterceptor({ method: 'post', url: '/v1/auth/login', headers: {} })
  const register = await requestInterceptor({ method: 'post', url: '/v1/auth/register', headers: {} })
  const refresh = await requestInterceptor({ method: 'post', url: '/v1/auth/refresh', headers: {} })
  const forgot = await requestInterceptor({ method: 'post', url: '/v1/auth/forgot-password', headers: {} })
  const reset = await requestInterceptor({ method: 'post', url: '/v1/auth/reset-password', headers: {} })

  expect(login.headers).toEqual({})
  expect(register.headers).toEqual({})
  expect(refresh.headers).toEqual({})
  expect(forgot.headers).toEqual({})
  expect(reset.headers).toEqual({})
  expect(transport.get).not.toHaveBeenCalled()
})

it('keeps password-reset secrets out of console diagnostics', async () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  try {
    await responseInterceptor({
      config: {
        url: '/v1/auth/reset-password',
        data: JSON.stringify({ token: 'raw-reset-token', new_password: 'hunter2hunter2' }),
        headers: {},
      },
      response: { status: 422, data: { detail: [{ loc: ['body', 'token'] }] } },
    }).catch(() => undefined)

    const logged = JSON.stringify(consoleError.mock.calls)
    expect(logged).toContain('/v1/auth/reset-password')
    expect(logged).not.toContain('raw-reset-token')
    expect(logged).not.toContain('hunter2hunter2')
  } finally {
    consoleError.mockRestore()
  }
})

it('keeps ordinary endpoint diagnostics unchanged', async () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  try {
    const error = {
      config: { url: '/v1/threads/42', data: JSON.stringify({ title: 'Saga' }), headers: {} },
      response: { status: 500, data: { detail: 'boom' } },
    }
    await responseInterceptor(error).catch(() => undefined)

    expect(consoleError).toHaveBeenCalledWith('API Error:', error)
  } finally {
    consoleError.mockRestore()
  }
})

it('matches absolute canonical client URLs by pathname', async () => {
  const login = await requestInterceptor({
    method: 'post',
    url: 'https://comic-pile.example/v1/auth/login?returnTo=/queue',
    headers: {},
  })

  expect(login.headers).toEqual({})
  expect(transport.get).not.toHaveBeenCalled()
})

it('does not exempt protected requests that only mention an auth path in the query', async () => {
  transport.get.mockResolvedValue({ csrf_token: 'fresh-token' })

  const config = await requestInterceptor({
    method: 'post',
    url: '/threads/9?returnTo=/v1/auth/login',
    headers: {},
  })

  expect(transport.get).toHaveBeenCalledWith('/v1/auth/csrf', { skipAuthRedirect: true })
  expect(config.headers).toEqual({ 'X-CSRF-Token': 'fresh-token' })
})

it('refreshes expired requests through the canonical v1 auth endpoint', async () => {
  transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
  transport.request.mockResolvedValue({ refreshed: true })

  const originalRequest = { url: '/v1/threads/42', headers: {} }
  const result = await responseInterceptor({
    config: originalRequest,
    response: { status: 401 },
  })

  expect(transport.post).toHaveBeenCalledWith('/v1/auth/refresh')
  expect(transport.request).toHaveBeenCalledWith({
    ...originalRequest,
    _retry: true,
    headers: { Authorization: 'Bearer refreshed-token' },
  })
  expect(result).toEqual({ refreshed: true })
})

it('refreshes a protected request whose query mentions an auth path', async () => {
  transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
  transport.request.mockResolvedValue({ refreshed: true })

  const originalRequest = { url: '/v1/threads/42?returnTo=/v1/auth/login', headers: {} }
  const result = await responseInterceptor({
    config: originalRequest,
    response: { status: 401 },
  })

  expect(transport.post).toHaveBeenCalledWith('/v1/auth/refresh')
  expect(transport.request).toHaveBeenCalledWith({
    ...originalRequest,
    _retry: true,
    headers: { Authorization: 'Bearer refreshed-token' },
  })
  expect(result).toEqual({ refreshed: true })
})
