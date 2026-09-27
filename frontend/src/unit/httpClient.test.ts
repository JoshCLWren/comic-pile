import { describe, expect, it, vi } from 'vitest'

import { defaultHttpClient, setDefaultHttpClient } from '../services/httpClient'
import { createHttpClientStub } from './httpClientStub'

describe('defaultHttpClient', () => {
  it('refuses to send a request before api.ts registers a transport', async () => {
    vi.resetModules()
    const unregistered = await import('../services/httpClient')

    expect(() => unregistered.defaultHttpClient().get('/v1/threads/')).toThrow(
      'The default HTTP client was requested before api.ts registered one',
    )
  })

  it('forwards every verb to the transport api.ts registered', async () => {
    const registered = createHttpClientStub()
    setDefaultHttpClient(registered)
    const client = defaultHttpClient()

    await client.get('/v1/threads/', { params: { search: 'bat' } })
    await client.post('/v1/roll/skip')
    await client.put('/v1/queues/9/name', { name: 'Saga' })
    await client.patch('/v1/roll/session-mode', { mode: 'auto' })
    await client.delete('/v1/queues/9')

    expect(registered.get).toHaveBeenCalledWith('/v1/threads/', {
      params: { search: 'bat' },
    })
    expect(registered.post).toHaveBeenCalledWith('/v1/roll/skip', undefined, undefined)
    expect(registered.put).toHaveBeenCalledWith(
      '/v1/queues/9/name',
      { name: 'Saga' },
      undefined,
    )
    expect(registered.patch).toHaveBeenCalledWith(
      '/v1/roll/session-mode',
      { mode: 'auto' },
      undefined,
    )
    expect(registered.delete).toHaveBeenCalledWith('/v1/queues/9', undefined)
  })

  it('resolves the transport registered after the singletons were built', async () => {
    const first = createHttpClientStub()
    setDefaultHttpClient(first)
    const client = defaultHttpClient()

    const second = createHttpClientStub()
    setDefaultHttpClient(second)
    await client.get('/v1/threads/')

    expect(first.get).not.toHaveBeenCalled()
    expect(second.get).toHaveBeenCalledWith('/v1/threads/', undefined)
  })
})
