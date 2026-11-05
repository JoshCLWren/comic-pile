import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
// SAFETY: createRollBootstrapApi returns a service whose get posts the session
// first and then reads the projection; the stub client satisfies HttpClient.
let rollBootstrapApi: ReturnType<typeof createRollBootstrapApi>

beforeEach(() => {
  client.post.mockReset().mockResolvedValue({ session_id: 1, created: false })
  client.get.mockReset().mockResolvedValue({ rollable: [], pool_reason: 'no_series' })
  // A fresh service per test keeps the client-lifetime session-resolution
  // dedupe (#4276) from leaking between cases.
  rollBootstrapApi = createRollBootstrapApi(client)
})

it('sends a valid browser IANA timezone as the bootstrap query parameter', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', { timezone: 'America/Chicago' })
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
})

it('keeps the canonical bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
  expect(client.get).toHaveBeenCalledTimes(1)
  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', {})
})

it('treats a blank timezone like a missing value instead of sending garbage', async () => {
  await rollBootstrapApi.get('')

  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', {})
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})

it('does not read bootstrap when explicit initialization fails', async () => {
  client.post.mockRejectedValueOnce(new Error('session init unavailable'))
  await expect(rollBootstrapApi.get()).rejects.toThrow('session init unavailable')
  expect(client.get).not.toHaveBeenCalled()
})

it('resolves the session only once across bootstrap refetches (#4276)', async () => {
  await rollBootstrapApi.get('America/Chicago')
  await rollBootstrapApi.get('America/Chicago')
  await rollBootstrapApi.get('America/Chicago')

  // One write for the client lifetime; every later fetch is the read-only
  // projection alone, so retries, reconciliation refreshes, and warm
  // navigation re-entries no longer re-pay the session write.
  expect(client.post).toHaveBeenCalledTimes(1)
  expect(client.get).toHaveBeenCalledTimes(3)
})

it('shares one in-flight session POST across concurrent first fetches (#4276)', async () => {
  const [first, second] = await Promise.all([
    rollBootstrapApi.get('America/Chicago'),
    rollBootstrapApi.get('America/Chicago'),
  ])

  expect(first).toMatchObject({ rollable: [], pool_reason: 'no_series' })
  expect(second).toEqual(first)
  expect(client.post).toHaveBeenCalledTimes(1)
  expect(client.get).toHaveBeenCalledTimes(2)
})

it('re-resolves exactly once when the read-only projection reports no active session (#4276)', async () => {
  client.get
    .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'No active session' } } })
    .mockResolvedValueOnce({ rollable: [], pool_reason: 'no_series' })

  // A pre-resolved client pays no write on its next fetch; the 404 proves the
  // session gap lapsed (or a different reader signed in), so one fresh POST
  // and one retried GET are the bounded recovery.
  await rollBootstrapApi.get('America/Chicago')
  client.get.mockReset().mockResolvedValue({ rollable: [], pool_reason: 'no_series' })
  const callsBefore = client.post.mock.calls.length
  client.get
    .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'No active session' } } })
    .mockResolvedValueOnce({ rollable: [], pool_reason: 'no_series' })

  await rollBootstrapApi.get('America/Chicago')

  expect(client.post.mock.calls.length - callsBefore).toBe(1)
  expect(client.get).toHaveBeenCalledTimes(2)
})

it('never re-posts the session for an authentication failure (#4276)', async () => {
  await rollBootstrapApi.get('America/Chicago')
  client.post.mockClear()
  client.get.mockRejectedValueOnce({ response: { status: 401, data: { detail: 'Not authenticated' } } })

  await expect(rollBootstrapApi.get('America/Chicago')).rejects.toEqual(
    expect.objectContaining({ response: expect.objectContaining({ status: 401 }) }),
  )
  expect(client.post).not.toHaveBeenCalled()
})

it('propagates a backend-unavailable failure without a session retry (#4276)', async () => {
  await rollBootstrapApi.get('America/Chicago')
  client.post.mockClear()
  client.get.mockRejectedValueOnce({ response: { status: 503, data: { detail: 'Database temporarily unavailable' } } })

  await expect(rollBootstrapApi.get('America/Chicago')).rejects.toEqual(
    expect.objectContaining({ response: expect.objectContaining({ status: 503 }) }),
  )
  expect(client.post).not.toHaveBeenCalled()
})

it('re-resolves when the browser timezone changes (#4276)', async () => {
  await rollBootstrapApi.get('America/Chicago')
  await rollBootstrapApi.get('Europe/London')

  // The stored session timezone tracks the reader's current zone, so a zone
  // change is a new resolution (one more write), never a skipped one.
  expect(client.post).toHaveBeenCalledTimes(2)
  expect(client.post).toHaveBeenLastCalledWith('/v2/reading-sessions', { timezone: 'Europe/London' })
})
