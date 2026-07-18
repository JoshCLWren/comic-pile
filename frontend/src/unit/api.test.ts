import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  request: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

const { get, post, put } = apiMock
const del = apiMock.delete

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { clearAccessToken, dependenciesApi, queueApi, setAccessToken, threadsApi } from '../services/api'

const requestInterceptor = apiMock.interceptors.request.use.mock.calls[0][0] as (
  config: { method?: string; url?: string; headers?: Record<string, string> }
) => Promise<{ method?: string; url?: string; headers?: Record<string, string> }>
const responseInterceptor = apiMock.interceptors.response.use.mock.calls[0][1] as (
  error: { config: { url: string; headers?: Record<string, string> }; response: { status: number } },
) => Promise<unknown>

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  put.mockReset()
  del.mockReset()
  get.mockResolvedValue({})
  post.mockResolvedValue({})
  put.mockResolvedValue({})
  del.mockResolvedValue({})
  apiMock.request.mockReset()
  clearAccessToken()
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

it('refreshes and retries a request after an expired access token', async () => {
  post.mockResolvedValue({ access_token: 'refreshed-token' })
  apiMock.request.mockResolvedValue({ refreshed: true })

  const originalRequest = { url: '/v1/threads/42/reading-orders', headers: {} }
  const result = await responseInterceptor({ config: originalRequest, response: { status: 401 } })

  expect(post).toHaveBeenCalledWith('/auth/refresh')
  expect(apiMock.request).toHaveBeenCalledWith({
    ...originalRequest,
    _retry: true,
    headers: { Authorization: 'Bearer refreshed-token' },
  })
  expect(result).toEqual({ refreshed: true })
})

it('calls thread endpoints with expected paths', () => {
  threadsApi.list()
  threadsApi.list({ search: 'bat' })
  threadsApi.get(9)

  expect(get).toHaveBeenCalledWith('/threads/', { params: undefined })
  expect(get).toHaveBeenCalledWith('/threads/', { params: { search: 'bat' } })
  expect(get).toHaveBeenCalledWith('/threads/9')
})

it('calls queue endpoints with expected paths', () => {
  queueApi.moveToPosition(3, 2)
  queueApi.moveToFront(4)
  queueApi.moveToBack(5)
  queueApi.shuffle()

  expect(put).toHaveBeenCalledWith('/queue/threads/3/position/', { new_position: 2 })
  expect(put).toHaveBeenCalledWith('/queue/threads/4/front/')
  expect(put).toHaveBeenCalledWith('/queue/threads/5/back/')
  expect(post).toHaveBeenCalledWith('/queue/shuffle/')
})

it('calls dependency endpoints with expected paths', () => {
  dependenciesApi.listBlockedThreadIds()
  dependenciesApi.listThreadDependencies(11)
  dependenciesApi.getBlockingInfo(12)
  dependenciesApi.createDependency({ sourceId: 1, targetId: 2 })
  dependenciesApi.deleteDependency(7)

  expect(get).toHaveBeenCalledWith('/v1/dependencies/blocked')
  expect(get).toHaveBeenCalledWith('/v1/threads/11/dependencies')
  expect(post).toHaveBeenCalledWith('/v1/threads/12:getBlockingInfo')
  expect(post).toHaveBeenCalledWith('/v1/dependencies/', {
    source_type: 'thread',
    source_id: 1,
    target_type: 'thread',
    target_id: 2,
  })
  expect(del).toHaveBeenCalledWith('/v1/dependencies/7')
})

it('adds auth and csrf headers to mutating requests', async () => {
  setAccessToken('access-token')
  document.cookie = 'csrf_token=cookie-token; path=/'

  const config = await requestInterceptor({
    method: 'post',
    url: '/threads/',
    headers: {},
  })

  expect(config.headers).toEqual({
    Authorization: 'Bearer access-token',
    'X-CSRF-Token': 'cookie-token',
  })
  expect(get).not.toHaveBeenCalled()
})

it('bootstraps a csrf token before protected requests when the cookie is missing', async () => {
  get.mockResolvedValue({ csrf_token: 'fresh-token' })

  const config = await requestInterceptor({
    method: 'delete',
    url: '/threads/9',
    headers: {},
  })

  expect(get).toHaveBeenCalledWith('/auth/csrf', { skipAuthRedirect: true })
  expect(config.headers).toEqual({ 'X-CSRF-Token': 'fresh-token' })
})
