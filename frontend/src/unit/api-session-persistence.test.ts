import { beforeEach, expect, it } from 'vitest'
import { createApiClient, getAccessToken, setAccessToken } from '../services/api'
import { createTransportDouble } from './transportDouble'

const transport = createTransportDouble()
createApiClient(() => transport as never)


const responseInterceptor = transport.interceptors.response.use.mock.calls[0][1] as (
  error: {
    config: { url: string; headers?: Record<string, string> }
    response: { status: number; data?: unknown }
  },
) => Promise<Record<string, string | number | boolean | null>>

beforeEach(() => {
  transport.post.mockReset()
  transport.request.mockReset()
  setAccessToken(null)
})

it.each([
  ['a cold-start server error', Object.assign(new Error('service unavailable'), { response: { status: 503 } })],
  ['a temporary network failure', new Error('network timeout')],
])('keeps the current session after %s during token refresh', async (_description, refreshError) => {
  setAccessToken('preserve-this-token')
  transport.post.mockRejectedValueOnce(refreshError)

  await expect(
    responseInterceptor({
      config: { url: '/v1/auth/me', headers: {} },
      response: { status: 401 },
    }),
  ).rejects.toBe(refreshError)

  expect(getAccessToken()).toBe('preserve-this-token')
  expect(transport.request).not.toHaveBeenCalled()
})
