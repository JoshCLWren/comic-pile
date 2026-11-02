import { describe, expect, test } from 'vitest'
import axios from 'axios'
import {
  canonicalQuery,
  canonicalRequest,
  describeRequests,
  installNetworkLedger,
} from './requestLedger'

describe('network ledger primitives', () => {
  test('canonical identities sort query keys and values', () => {
    expect(canonicalQuery({ b: ['2', '1'], a: ['z'] })).toBe('a=z&b=1&b=2')
    expect(canonicalRequest('get', '/api/v1/thing', { b: ['2'], a: ['1'] })).toBe(
      'GET /api/v1/thing?a=1&b=2',
    )
  })

  test('records the real axios method, baseURL path, and query', async () => {
    const client = axios.create({ baseURL: '/api' })
    const ledger = installNetworkLedger(client, {
      handlers: { 'GET /api/v1/thing': () => ({ data: { ok: true } }) },
    })

    const payload = await client.get('/v1/thing', { params: { z: '2', a: '1' } })

    expect(payload.data).toEqual({ ok: true })
    expect(ledger.requests()).toHaveLength(1)
    expect(ledger.requests()[0]).toMatchObject({
      method: 'GET',
      path: '/api/v1/thing',
      query: { z: ['2'], a: ['1'] },
      url: 'GET /api/v1/thing?a=1&z=2',
    })
    expect(describeRequests(ledger.requests())).toEqual(['GET /api/v1/thing?a=1&z=2 x1'])
  })

  test('reports concurrent duplicates and unhandled keys', async () => {
    const client = axios.create({ baseURL: '/api' })
    const ledger = installNetworkLedger(client)

    await Promise.all([client.get('/v1/thing'), client.get('/v1/thing')])
    await client.post('/v1/other', { value: 1 })

    expect(ledger.duplicates()).toEqual({ 'GET /api/v1/thing': 2 })
    expect(ledger.unhandled()).toEqual(['GET /api/v1/thing', 'POST /api/v1/other'])
  })

  test('scopes requests to a measurement window', async () => {
    const client = axios.create({ baseURL: '/api' })
    const ledger = installNetworkLedger(client)

    await client.get('/v1/first')
    const marker = ledger.mark()
    await client.get('/v1/second')

    expect(ledger.since(marker).map(request => request.path)).toEqual(['/api/v1/second'])
  })
})
