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
  error: { config: { url: string; headers?: Record<string, string>; skipAuthRedirect?: boolean }; response: { status: number } },
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

it('calls thread endpoints with expected paths', async () => {
  await threadsApi.list()
  await threadsApi.list({ search: 'bat' })
  await threadsApi.get(9)

  expect(get).toHaveBeenCalledWith('/threads/', { params: undefined })
  expect(get).toHaveBeenCalledWith('/threads/', { params: { search: 'bat' } })
  expect(get).toHaveBeenCalledWith('/threads/9')
})

it('calls queue endpoints with expected paths', async () => {
  await queueApi.moveToPosition(3, 2)
  await queueApi.moveToFront(4)
  await queueApi.moveToBack(5)
  await queueApi.shuffle()

  expect(put).toHaveBeenCalledWith('/queue/threads/3/position/', { new_position: 2 })
  expect(put).toHaveBeenCalledWith('/queue/threads/4/front/')
  expect(put).toHaveBeenCalledWith('/queue/threads/5/back/')
  expect(post).toHaveBeenCalledWith('/queue/shuffle/')
})

it('calls dependency endpoints with expected paths', async () => {
  await dependenciesApi.listBlockedThreadIds()
  await dependenciesApi.listThreadDependencies(11)
  await dependenciesApi.getBlockingInfo(12)
  await dependenciesApi.createDependency({ sourceId: 1, targetId: 2 })
  await dependenciesApi.deleteDependency(7)

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
  await threadsApi.create({ title: 'T', format: 'Comic', issues_remaining: 1 })
  await threadsApi.update(1, { title: 'Updated' })
  await threadsApi.delete(1)
  await threadsApi.reactivate({ thread_id: 1, issues_to_add: 2 })
  await threadsApi.listStale()
  await threadsApi.listStale(7)
  await threadsApi.setPending(1)
  await rollApi.roll()
  await rollApi.override({ thread_id: 1 })
  await rollApi.dismissPending()
  await rollApi.reroll()
  await rollApi.setDie(6)
  await rollApi.clearManualDie()
  await rateApi.rate({ thread_id: 1, rating: 4 })
  await sessionApi.list({ status: 'complete' }, 'page')
  await sessionApi.get(1)
  await sessionApi.getCurrent()
  await sessionApi.getDetails('2')
  await sessionApi.getSnapshots(2)
  await sessionApi.restoreSessionStart(2)
  await undoApi.undo(1, 'snap')
  await undoApi.listSnapshots(1)
  await dependenciesApi.getIssueDependencies(2)
  await dependenciesApi.getConnectedThreads(1)
  await dependenciesApi.updateDependency(3, null)
  await tasksApi.getMetrics()
  await snoozeApi.snooze()
  await snoozeApi.unsnooze(2)
  await collectionsApi.list()
  await collectionsApi.get(1)
  await collectionsApi.create({ name: 'C', position: 1 })
  await collectionsApi.update(1, { name: 'D' })
  await collectionsApi.delete(1)
  await collectionsApi.moveThreadToCollection(2, null)
  await migrationApi.migrateThread(1, { last_issue_read: 2, total_issues: 3 })
  await bugReportsApi.create({ title: 'Bug', description: 'Description', diagnostics: {} })
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

it('handles request defaults and issue dependency payloads', async () => {
  const config = await requestInterceptor({})
  expect(config.headers).toEqual({})
  await dependenciesApi.createDependency({
    sourceType: 'issue', sourceId: 8, targetType: 'issue', targetId: 9,
  })
  expect(post).toHaveBeenCalledWith('/v1/dependencies/', {
    source_type: 'issue', source_id: 8, target_type: 'issue', target_id: 9,
  })
  await sessionApi.list()
  expect(get).toHaveBeenCalledWith('/sessions/', { params: undefined })
})

it('handles missing request URLs and cookies while sharing csrf bootstrap work', async () => {
  document.cookie = 'unrelated=value; path=/'
  let resolveCsrf: (value: { csrf_token: string }) => void = () => {}
  get.mockImplementationOnce(() => new Promise((resolve) => { resolveCsrf = resolve }))

  const first = requestInterceptor({ method: 'post', headers: {} })
  const second = requestInterceptor({ method: 'post', headers: {} })
  await Promise.resolve()
  resolveCsrf({ csrf_token: 'shared-csrf' })

  await expect(first).resolves.toEqual(expect.objectContaining({
    headers: { 'X-CSRF-Token': 'shared-csrf' },
  }))
  await expect(second).resolves.toEqual(expect.objectContaining({
    headers: { 'X-CSRF-Token': 'shared-csrf' },
  }))
  expect(get).toHaveBeenCalledTimes(1)
})

it('does not attach csrf to safe or exempt requests', async () => {
  setAccessToken(null)
  const getConfig = await requestInterceptor({ method: 'get', url: '/threads/', headers: {} })
  expect(getConfig.headers).toEqual({})
  const loginConfig = await requestInterceptor({ method: 'post', url: '/auth/login', headers: {} })
  expect(loginConfig.headers).toEqual({})
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
  await expect(responseInterceptor({ config: {}, response: { status: 500 } } as never)).rejects.toEqual(expect.objectContaining({ response: { status: 500 } }))
  await expect(responseInterceptor({ config: { url: '/auth/login' }, response: { status: 401 } })).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
  await expect(responseInterceptor({ config: { url: '/x', _retry: true } as never, response: { status: 401 } })).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
})

it('rejects a failed token refresh without retrying the original request', async () => {
  post.mockRejectedValueOnce(new Error('refresh failed'))
  await expect(responseInterceptor({ config: { url: '/threads/1' }, response: { status: 401 } })).rejects.toThrow('refresh failed')
  expect(apiMock.request).not.toHaveBeenCalled()
})

it('redirects to login when the refresh endpoint itself returns unauthorized', async () => {
  window.history.pushState({}, '', '/queue')
  await expect(responseInterceptor({
    config: { url: '/auth/refresh' },
    response: { status: 401 },
  })).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
  window.history.pushState({}, '', '/')
})

it('queues concurrent unauthorized requests behind a single refresh', async () => {
  let resolveRefresh: (value: { access_token: string }) => void = () => {}
  post.mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
  apiMock.request.mockResolvedValue({ ok: true })

  const first = responseInterceptor({ config: { url: '/threads/1' }, response: { status: 401 } })
  const second = responseInterceptor({ config: { url: '/threads/2' }, response: { status: 401 } })
  await Promise.resolve()
  resolveRefresh({ access_token: 'shared-token' })
  await expect(first).resolves.toEqual({ ok: true })
  await expect(second).resolves.toEqual({ ok: true })
  expect(post).toHaveBeenCalledTimes(1)
  expect(apiMock.request).toHaveBeenCalledWith(expect.objectContaining({
    url: '/threads/2',
    headers: { Authorization: 'Bearer shared-token' },
  }))
})

it('covers csrf fallback, redirect guards, and queued refresh rejection', async () => {
  setAccessToken('token')
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  get.mockResolvedValue({ csrf_token: undefined })
  const config = await requestInterceptor({ method: 'put', url: '/threads/1', headers: {} })
  expect(config.headers).toEqual({ Authorization: 'Bearer token' })
  expect(get).toHaveBeenCalledWith('/auth/csrf', { skipAuthRedirect: true })

  window.history.pushState({}, '', '/login')
  await expect(responseInterceptor({ config: { url: '/auth/refresh' }, response: { status: 401 } })).rejects.toBeDefined()
  window.history.pushState({}, '', '/queue')

  let rejectRefresh: (reason: Error) => void = () => {}
  post.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRefresh = reject }))
  const first = responseInterceptor({ config: { url: '/threads/first' }, response: { status: 401 } })
  const second = responseInterceptor({ config: { url: '/threads/second' }, response: { status: 401 } })
  await Promise.resolve()
  rejectRefresh(Object.assign(new Error('refresh unauthorized'), { response: { status: 401 } }))
  await expect(first).rejects.toThrow('refresh unauthorized')
  await expect(second).rejects.toEqual(expect.objectContaining({ response: { status: 401 } }))
})

it('preserves queued request headers and avoids redirecting skipped refresh failures', async () => {
  let resolveRefresh: (value: { access_token: string }) => void = () => {}
  post.mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
  apiMock.request.mockResolvedValue({ ok: true })

  const first = responseInterceptor({ config: { url: '/threads/first' }, response: { status: 401 } })
  const second = responseInterceptor({
    config: { url: '/threads/second', headers: {} },
    response: { status: 401 },
  })
  await Promise.resolve()
  resolveRefresh({ access_token: 'queued-token' })
  await expect(first).resolves.toEqual({ ok: true })
  await expect(second).resolves.toEqual({ ok: true })
  expect(apiMock.request).toHaveBeenCalledWith(expect.objectContaining({
    url: '/threads/second',
    headers: { Authorization: 'Bearer queued-token' },
  }))

  post.mockRejectedValueOnce(Object.assign(new Error('skipped refresh'), { response: { status: 503 } }))
  await expect(responseInterceptor({
    config: { url: '/threads/3', skipAuthRedirect: true },
    response: { status: 401 },
  })).rejects.toThrow('skipped refresh')
})
