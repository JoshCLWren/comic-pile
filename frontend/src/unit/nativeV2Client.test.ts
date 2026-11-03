import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  compactQuery,
  createNativeV2Client,
  type NativeV2Client,
} from '../generated/nativeV2Client'
import { createApiClient } from '../services/api'
import { createQueueApi } from '../services/api-queue'
import { createTransportDouble } from './transportDouble'

type TransportMethod = 'get' | 'post' | 'put' | 'patch' | 'delete'

interface ClientCase {
  name: string
  invoke: (client: NativeV2Client) => Promise<object | null | undefined>
  method: TransportMethod
  expectedArgs: unknown[]
}

function clientWithTransport() {
  const transport = createTransportDouble()
  return { transport, client: createApiClient(() => transport) }
}

const clientCases: ClientCase[] = [
  {
    name: 'bootstraps with the optional timezone query',
    invoke: (client) => client.bootstrap({ query: { timezone: 'UTC' } }),
    method: 'get',
    expectedArgs: ['/v2/roll/bootstrap', { params: { timezone: 'UTC' } }],
  },
  {
    name: 'bootstraps without query values',
    invoke: (client) => client.bootstrap(),
    method: 'get',
    expectedArgs: ['/v2/roll/bootstrap', { params: undefined }],
  },
  {
    name: 'creates a queue order',
    invoke: (client) =>
      client.createQueueOrder({ body: { idempotency_key: 'shuffle-key-1' } }),
    method: 'post',
    expectedArgs: ['/v2/queue-orders', { idempotency_key: 'shuffle-key-1' }],
  },
  {
    name: 'reads the CSRF token',
    invoke: (client) => client.csrf(),
    method: 'get',
    expectedArgs: ['/v2/auth/csrf'],
  },
  {
    name: 'requests a password-recovery email',
    invoke: (client) => client.forgotPassword({ body: { email: 'reader@example.com' } }),
    method: 'post',
    expectedArgs: ['/v2/auth/forgot-password', { email: 'reader@example.com' }],
  },
  {
    name: 'reads one queue entry by encoded path id',
    invoke: (client) => client.getQueueEntry({ path: { thread_id: 42 } }),
    method: 'get',
    expectedArgs: ['/v2/queue-entries/42'],
  },
  {
    name: 'initializes a reading session',
    invoke: (client) => client.initializeSession({ body: { timezone: 'UTC' } }),
    method: 'post',
    expectedArgs: ['/v2/reading-sessions', { timezone: 'UTC' }],
  },
  {
    name: 'reads issue cards in a bounded batch',
    invoke: (client) => client.issueCards({ body: { issue_ids: [1, 2] } }),
    method: 'post',
    expectedArgs: ['/v2/issues/cards', { issue_ids: [1, 2] }],
  },
  {
    name: 'patches issue read state by encoded path id',
    invoke: (client) =>
      client.issueReadRate({
        path: { issue_id: 7 },
        body: { status: 'read', rating: 4, idempotency_key: 'read-key' },
      }),
    method: 'patch',
    expectedArgs: [
      '/v2/issues/7',
      { status: 'read', rating: 4, idempotency_key: 'read-key' },
    ],
  },
  {
    name: 'lists threads without query values',
    invoke: (client) => client.listThreads(),
    method: 'get',
    expectedArgs: ['/v2/threads', { params: undefined }],
  },
  {
    name: 'lists threads with present query values and drops absent ones',
    invoke: (client) =>
      client.listThreads({
        query: { search: 'bat', sort: undefined, page_size: 25 },
      }),
    method: 'get',
    expectedArgs: ['/v2/threads', { params: { search: 'bat', page_size: 25 } }],
  },
  {
    name: 'lists threads with an empty query object',
    invoke: (client) => client.listThreads({ query: {} }),
    method: 'get',
    expectedArgs: ['/v2/threads', { params: undefined }],
  },
  {
    name: 'logs in with generated credentials',
    invoke: (client) => client.login({ body: { username: 'reader', password: 'secret1' } }),
    method: 'post',
    expectedArgs: ['/v2/auth/login', { username: 'reader', password: 'secret1' }],
  },
  {
    name: 'logs out without a body',
    invoke: (client) => client.logout().then(() => null),
    method: 'post',
    expectedArgs: ['/v2/auth/logout'],
  },
  {
    name: 'sends a manual die command',
    invoke: (client) =>
      client.manualDie({
        body: { kind: 'manual_select', die: 6, idempotency_key: 'die-key' },
      }),
    method: 'post',
    expectedArgs: [
      '/v2/roll/dice-command',
      { kind: 'manual_select', die: 6, idempotency_key: 'die-key' },
    ],
  },
  {
    name: 'reads the current account',
    invoke: (client) => client.me(),
    method: 'get',
    expectedArgs: ['/v2/auth/me'],
  },
  {
    name: 'requests a Roll offer',
    invoke: (client) =>
      client.offer({
        body: { timezone: 'UTC', snoozed_thread_ids: [3], idempotency_key: 'offer-key' },
      }),
    method: 'post',
    expectedArgs: [
      '/v2/roll/offer',
      { timezone: 'UTC', snoozed_thread_ids: [3], idempotency_key: 'offer-key' },
    ],
  },
  {
    name: 'requests reading-boundary explanations',
    invoke: (client) => client.readingBoundaryBatch({ body: { thread_ids: [1, 2] } }),
    method: 'post',
    expectedArgs: ['/v2/reading-boundaries', { thread_ids: [1, 2] }],
  },
  {
    name: 'refreshes with no body (cookie authority)',
    invoke: (client) => client.refresh(),
    method: 'post',
    expectedArgs: ['/v2/auth/refresh', undefined],
  },
  {
    name: 'refreshes with an explicit token body',
    invoke: (client) => client.refresh({ body: { refresh_token: 'refresh-token' } }),
    method: 'post',
    expectedArgs: ['/v2/auth/refresh', { refresh_token: 'refresh-token' }],
  },
  {
    name: 'registers a new account',
    invoke: (client) =>
      client.register({
        body: { username: 'reader', email: 'reader@example.com', password: 'secret1' },
      }),
    method: 'post',
    expectedArgs: [
      '/v2/auth/register',
      { username: 'reader', email: 'reader@example.com', password: 'secret1' },
    ],
  },
  {
    name: 'resets the die',
    invoke: (client) => client.reset({ body: { idempotency_key: 'reset-key' } }),
    method: 'post',
    expectedArgs: ['/v2/roll/reset', { idempotency_key: 'reset-key' }],
  },
  {
    name: 'completes a password reset',
    invoke: (client) =>
      client.resetPassword({ body: { token: 'reset-token', new_password: 'secret2' } }),
    method: 'post',
    expectedArgs: [
      '/v2/auth/reset-password',
      { token: 'reset-token', new_password: 'secret2' },
    ],
  },
  {
    name: 'updates a queue entry position',
    invoke: (client) =>
      client.updateQueueEntry({ path: { thread_id: 3 }, body: { position: 2 } }),
    method: 'patch',
    expectedArgs: ['/v2/queue-entries/3', { position: 2 }],
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('generated native v2 request client transport', () => {
  it.each(clientCases)('$name', async ({ invoke, method, expectedArgs }) => {
    const { transport, client } = clientWithTransport()

    await invoke(createNativeV2Client(client))

    expect(transport[method]).toHaveBeenCalledTimes(1)
    expect(transport[method].mock.calls[0]).toEqual(expectedArgs)
  })

  it('returns the transport payload unchanged', async () => {
    const { transport, client } = clientWithTransport()
    const payload = { id: 7, username: 'reader', is_admin: false }
    transport.get.mockResolvedValueOnce(payload)

    await expect(createNativeV2Client(client).me()).resolves.toBe(payload)
  })

  it('propagates transport errors unchanged', async () => {
    const { transport, client } = clientWithTransport()
    const error = new Error('csrf token missing')
    transport.patch.mockRejectedValueOnce(error)

    await expect(
      createNativeV2Client(client).updateQueueEntry({
        path: { thread_id: 3 },
        body: { position: 2 },
      }),
    ).rejects.toBe(error)
  })

  it('does not bypass the shared transport or add its own headers', async () => {
    const { transport, client } = clientWithTransport()

    await createNativeV2Client(client).updateQueueEntry({
      path: { thread_id: 3 },
      body: { position: 2 },
    })

    expect(transport.request).not.toHaveBeenCalled()
    expect(transport.patch.mock.calls[0]).toHaveLength(2)
  })
})

describe('generated query helper', () => {
  it('drops absent, null and empty query values', () => {
    expect(compactQuery(undefined)).toBeUndefined()
    expect(compactQuery({})).toBeUndefined()
    expect(
      compactQuery({ search: undefined, sort: null, page_size: 25 }),
    ).toEqual({ page_size: 25 })
  })
})

describe('queue adapter through the generated native client', () => {
  it('preserves move, max back rank and shuffle idempotency behavior', async () => {
    const { transport, client } = clientWithTransport()
    const queueApi = createQueueApi(client)

    await queueApi.moveToPosition(3, 2)
    await queueApi.moveToFront(4)
    await queueApi.moveToBack(5)
    await queueApi.shuffle('shuffle-key-1')

    expect(transport.patch.mock.calls).toEqual([
      ['/v2/queue-entries/3', { position: 2 }],
      ['/v2/queue-entries/4', { position: 1 }],
      ['/v2/queue-entries/5', { position: 2_147_483_647 }],
    ])
    expect(transport.post.mock.calls).toEqual([
      ['/v2/queue-orders', { idempotency_key: 'shuffle-key-1' }],
    ])
  })

  it('generates a fallback shuffle key when the caller omits one', async () => {
    const { transport, client } = clientWithTransport()
    vi.stubGlobal('crypto', { randomUUID: () => 'generated-key' })
    const queueApi = createQueueApi(client)

    await expect(queueApi.shuffle()).resolves.toBeUndefined()

    expect(transport.post.mock.calls).toEqual([
      ['/v2/queue-orders', { idempotency_key: 'generated-key' }],
    ])
  })
})
