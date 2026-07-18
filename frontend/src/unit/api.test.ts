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

const { get, post, put } = apiMock
const del = apiMock.delete
const patch = apiMock.patch

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { bugReportsApi, clearAccessToken, collectionsApi, dependenciesApi, migrationApi, queueApi, rateApi, rollApi, sessionApi, setAccessToken, snoozeApi, tasksApi, threadsApi, undoApi } from '../services/api'

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
  patch.mockReset()
  get.mockResolvedValue({})
  post.mockResolvedValue({})
  put.mockResolvedValue({})
  del.mockResolvedValue({})
  patch.mockResolvedValue({})
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

it('calls every remaining API resource endpoint', async () => {
  await threadsApi.list(undefined, 'next')
  threadsApi.create({ title: 'T', format: 'Comic', issues_remaining: 1 })
  threadsApi.update(1, { title: 'Updated' })
  threadsApi.delete(1)
  threadsApi.reactivate({ thread_id: 1, issues_to_add: 2 })
  threadsApi.listStale()
  threadsApi.listStale(7)
  threadsApi.setPending(1)
  rollApi.roll(); rollApi.override({ thread_id: 1 }); rollApi.dismissPending(); rollApi.reroll(); rollApi.setDie(6); rollApi.clearManualDie()
  rateApi.rate({ thread_id: 1, rating: 4 })
  await sessionApi.list({ status: 'complete' }, 'page')
  sessionApi.get(1); sessionApi.getCurrent(); sessionApi.getDetails('2'); sessionApi.getSnapshots(2); sessionApi.restoreSessionStart(2)
  undoApi.undo(1, 'snap'); undoApi.listSnapshots(1)
  dependenciesApi.getIssueDependencies(2); dependenciesApi.getConnectedThreads(1); dependenciesApi.updateDependency(3, null)
  tasksApi.getMetrics(); snoozeApi.snooze(); snoozeApi.unsnooze(2)
  collectionsApi.list(); collectionsApi.get(1); collectionsApi.create({ name: 'C', position: 1 }); collectionsApi.update(1, { name: 'D' }); collectionsApi.delete(1); collectionsApi.moveThreadToCollection(2, null)
  migrationApi.migrateThread(1, { last_issue_read: 2, total_issues: 3 })
  bugReportsApi.create({ title: 'Bug', description: 'Description', diagnostics: {} })
  expect(get).toHaveBeenCalledWith('/v1/collections/')
  expect(post).toHaveBeenCalledWith('/bug-reports/', { title: 'Bug', description: 'Description', diagnostics: {} })
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

it('handles response success, network errors, validation errors, and auth errors', async () => {
  const success = await (apiMock.interceptors.response.use.mock.calls[0][0] as (response: { data: unknown }) => unknown)({ data: { ok: true } })
  expect(success).toEqual({ ok: true })
  await expect(responseInterceptor({ config: { url: '/x' }, response: undefined } as never)).rejects.toThrow('Network error')
  await expect(responseInterceptor({ config: { url: '/x' }, response: { status: 400 } } as never)).rejects.toEqual(expect.objectContaining({ response: { status: 400 } }))
  await expect(responseInterceptor({ config: { url: '/auth/login' }, response: { status: 401 } })).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
  await expect(responseInterceptor({ config: { url: '/x', _retry: true } as never, response: { status: 401 } })).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
})
