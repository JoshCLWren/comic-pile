import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApiClient, getAccessToken, setAccessToken } from '../services/api'
import type { ApiRequestConfig } from '../services/httpClient'
import { createTransportDouble } from './transportDouble'

const transport = createTransportDouble()
createApiClient(() => transport)
const responseError = transport.interceptors.response.use.mock.calls[0][1] as (
  error: { config?: ApiRequestConfig; response?: { status: number; data?: unknown }; message?: string },
) => Promise<unknown>

beforeEach(() => {
  transport.post.mockReset()
  transport.request.mockReset()
  setAccessToken('current-session')
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

it('rejects all queued requests on a temporary refresh outage and allows later recovery', async () => {
  let rejectRefresh: (reason: Error) => void = () => {}
  const refresh = new Promise<{ access_token: string }>((_resolve, reject) => {
    rejectRefresh = reject
  })
  const outage = Object.assign(new Error('temporarily unavailable'), { response: { status: 503 } })
  transport.post.mockReturnValueOnce(refresh)
  const first = responseError({
    config: { url: '/v1/threads/1', skipAuthRedirect: true }, response: { status: 401 },
  })
  const queued = responseError({
    config: { url: '/v1/threads/2', skipAuthRedirect: true }, response: { status: 401 },
  })
  const rejected = Promise.all([
    expect(first).rejects.toBe(outage),
    expect(queued).rejects.toBe(outage),
  ])
  rejectRefresh(outage)
  await rejected

  expect(transport.post).toHaveBeenCalledTimes(1)
  expect(transport.request).not.toHaveBeenCalled()
  expect(getAccessToken()).toBe('current-session')

  transport.post.mockResolvedValueOnce({ access_token: 'recovered-session' })
  transport.request.mockResolvedValueOnce({ id: 3 })
  await expect(responseError({
    config: { url: '/v1/threads/3', skipAuthRedirect: true }, response: { status: 401 },
  })).resolves.toEqual({ id: 3 })
  expect(transport.post).toHaveBeenCalledTimes(2)
  expect(transport.request).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
    url: '/v1/threads/3', headers: { Authorization: 'Bearer recovered-session' },
  }))
})

it.each([undefined, null, { detail: 'Permission denied' }])(
  'keeps a forbidden response with body %j distinct from expired authentication', async (data) => {
    const forbidden = { config: { url: '/v1/threads/1' }, response: { status: 403, data } }
    await expect(responseError(forbidden)).rejects.toBe(forbidden)
    expect(transport.post).not.toHaveBeenCalled()
    expect(getAccessToken()).toBe('current-session')
  },
)

it('reports a transport failure without request metadata while preserving the session', async () => {
  await expect(responseError({ message: 'connection closed' })).rejects.toThrow('Network error')
  expect(transport.post).not.toHaveBeenCalled()
  expect(getAccessToken()).toBe('current-session')
})
