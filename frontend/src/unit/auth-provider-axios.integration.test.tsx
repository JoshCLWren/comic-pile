import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import { AuthProvider, useAuth } from '../App'
import type { AuthContextValue } from '../contexts/AuthContext'
import api, { getAccessToken, setAccessToken } from '../services/api'

const user = { username: 'reader', email: 'reader@example.com' }
let auth: AuthContextValue
let calls: string[]
let replies: Array<(config: InternalAxiosRequestConfig) => ReturnType<AxiosAdapter>>
const originalAdapter = api.defaults.adapter

function reply(status = 200, data: unknown = user) {
  replies.push(async config => {
    const response = { status, data, statusText: String(status), headers: {}, config }
    if (status >= 400) throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, undefined, response)
    return response
  })
}
function transportFailure(code: string) {
  replies.push(async config => { throw new AxiosError('Transport failed', code, config) })
}
function Consumer() {
  auth = useAuth()
  return <output>{auth.authState.status}</output>
}
async function mount() {
  reply()
  render(<AuthProvider><Consumer /></AuthProvider>)
  await waitFor(() => expect(auth.authState.status).toBe('authenticated'))
  expect(calls).toEqual(['get /v1/auth/me'])
  calls.length = 0
}
beforeEach(() => {
  calls = []
  replies = []
  setAccessToken('existing-token')
  api.defaults.adapter = async config => {
    calls.push(`${config.method} ${config.url}`)
    const respond = replies.shift()
    if (!respond) throw new Error(`Unexpected request: ${config.method} ${config.url}`)
    return respond(config)
  }
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  cleanup()
  api.defaults.adapter = originalAdapter
  setAccessToken(null)
  vi.restoreAllMocks()
})

describe('AuthProvider with the real Axios interceptor pipeline', () => {
  it('validates a current token without refreshing', async () => {
    await mount()
    reply()
    await act(async () => auth.retryAuth())
    expect(calls).toEqual(['get /v1/auth/me'])
    expect(auth.authState.status).toBe('authenticated')
    expect(getAccessToken()).toBe('existing-token')
  })
  it.each(['503', 'timeout', 'network'])('preserves the session on %s and recovers without rotation', async failure => {
    await mount()
    if (failure === '503') reply(503)
    else transportFailure(failure === 'timeout' ? 'ECONNABORTED' : 'ERR_NETWORK')
    await act(async () => { await expect(auth.retryAuth()).rejects.toSatisfy(axios.isAxiosError) })
    expect(auth.authState.status).toBe(failure === 'network' ? 'network_error' : 'service_unavailable')
    expect(auth.user).toEqual(user)
    expect(getAccessToken()).toBe('existing-token')
    reply()
    await act(async () => auth.retryAuth())
    expect(calls).toEqual(['get /v1/auth/me', 'get /v1/auth/me'])
    expect(auth.authState.status).toBe('authenticated')
  })
  it.each([401, 403])('refreshes once after auth %i then validates once', async status => {
    await mount()
    reply(status, { detail: 'Not authenticated' })
    reply(200, { access_token: 'renewed-token' })
    reply()
    await act(async () => auth.retryAuth())
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh', 'get /v1/auth/me'])
    expect(auth.authState.status).toBe('authenticated')
    expect(getAccessToken()).toBe('renewed-token')
  })
  it('does not rotate again when post-refresh validation is rejected', async () => {
    await mount()
    reply(401)
    reply(200, { access_token: 'renewed-token' })
    reply(401)
    await act(async () => { await expect(auth.retryAuth()).rejects.toMatchObject({ response: { status: 401 } }) })
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh', 'get /v1/auth/me'])
    expect(auth.authState.status).toBe('unauthenticated')
    expect(getAccessToken()).toBeNull()
  })
  it.each([401, 403])('ends the session after refresh auth %i without another cookie probe', async status => {
    await mount()
    reply(401)
    reply(status, { detail: 'Not authenticated' })
    await act(async () => { await expect(auth.retryAuth()).rejects.toMatchObject({ response: { status } }) })
    expect(auth.authState.status).toBe('unauthenticated')
    expect(getAccessToken()).toBeNull()
    await act(async () => { await expect(auth.retryAuth()).rejects.toMatchObject({ response: { status: 401 } }) })
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh'])
  })
  it.each(['503', 'timeout', 'network'])('keeps the token when refresh fails with %s', async failure => {
    await mount()
    reply(401)
    if (failure === '503') reply(503)
    else transportFailure(failure === 'timeout' ? 'ECONNABORTED' : 'ERR_NETWORK')
    await act(async () => { await expect(auth.retryAuth()).rejects.toSatisfy(axios.isAxiosError) })
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh'])
    expect(getAccessToken()).toBe('existing-token')
    expect(auth.user).toEqual(user)
    expect(auth.authState.status).toBe(failure === 'network' ? 'network_error' : 'service_unavailable')
    reply()
    await act(async () => auth.retryAuth())
    expect(auth.authState.status).toBe('authenticated')
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh', 'get /v1/auth/me'])
  })
  it('coalesces bootstrap, resume, and rapid retry into one validation and refresh', async () => {
    let release!: () => void
    replies.push(config => new Promise((_resolve, reject) => {
      release = () => reject(new AxiosError('Expired', 'ERR_BAD_RESPONSE', config, undefined,
        { status: 401, data: {}, statusText: 'Unauthorized', headers: {}, config }))
    }))
    reply(200, { access_token: 'renewed-token' })
    reply()
    render(<AuthProvider><Consumer /></AuthProvider>)
    await waitFor(() => expect(calls).toHaveLength(1))
    await act(async () => {
      const attempts = [auth.retryAuth(), auth.retryAuth(), auth.revalidateSession()]
      release()
      await Promise.all(attempts)
    })
    expect(calls).toEqual(['get /v1/auth/me', 'post /v1/auth/refresh', 'get /v1/auth/me'])
    expect(auth.authState.status).toBe('authenticated')
  })
  it.each([
    ['success', 'logout'], ['401', 'logout'], ['503', 'logout'],
    ['success', 'login'], ['401', 'login'], ['503', 'login'],
  ])('ignores a late refresh %s after %s', async (outcome, action) => {
    await mount()
    reply(401)
    let finish!: () => void
    replies.push(config => new Promise((resolve, reject) => {
      finish = () => {
        const response = { status: outcome === 'success' ? 200 : Number(outcome), data: { access_token: 'old-token' }, statusText: '', headers: {}, config }
        if (outcome === 'success') resolve(response)
        else reject(new AxiosError('Failed', 'ERR_BAD_RESPONSE', config, undefined, response))
      }
    }))
    let pending!: Promise<void>
    act(() => { pending = auth.retryAuth() })
    await waitFor(() => expect(calls).toHaveLength(2))
    if (action === 'logout') act(() => auth.logout())
    else {
      reply(200, { username: 'second', email: 'second@example.com' })
      await act(async () => auth.login('second-token'))
    }
    await act(async () => { finish(); await pending })
    expect(auth.authState.status).toBe(action === 'logout' ? 'unauthenticated' : 'authenticated')
    expect(auth.user?.username ?? null).toBe(action === 'logout' ? null : 'second')
    expect(getAccessToken()).toBe(action === 'logout' ? null : 'second-token')
    expect(calls).toEqual(action === 'logout'
      ? ['get /v1/auth/me', 'post /v1/auth/refresh']
      : ['get /v1/auth/me', 'post /v1/auth/refresh', 'get /v1/auth/me'])
  })
})
