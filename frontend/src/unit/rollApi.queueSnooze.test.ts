import { beforeEach, expect, it } from 'vitest'
import { createRollApi } from '../services/api-roll'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()

beforeEach(() => {
  globalThis.sessionStorage?.removeItem('comicpile:roll:pending-offer')
  globalThis.document.cookie = 'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  client.get.mockReset().mockResolvedValue({ rollable: [], pool_reason: 'no_series' })
  client.post.mockReset().mockResolvedValue({})
})

it('scopes a Queue reroll to the exact pending comic (#4589)', async () => {
  const isolated = createRollApi(client)
  await isolated.reroll(42)

  expect(client.post).toHaveBeenCalledWith(
    '/v2/roll/offer',
    expect.objectContaining({
      expected_pending_thread_id: 42,
      idempotency_key: expect.stringMatching(/^roll-offer-[0-9a-f]{32}$/),
    }),
  )
  expect(client.post).not.toHaveBeenCalledWith('/v1/snooze/', expect.anything())
})

it('tracks and clears native temporary snoozes in the browser cookie', () => {
  const isolated = createRollApi(client)
  globalThis.document.cookie = 'comicpile_roll_snoozes=%5B42%5D; path=/; SameSite=Lax'

  expect(isolated.isTemporarilySnoozed(42)).toBe(true)
  expect(isolated.isTemporarilySnoozed(43)).toBe(false)

  isolated.unsnoozeTemporary(42)

  expect(isolated.isTemporarilySnoozed(42)).toBe(false)
})

it('does not reuse an unanswered Queue offer key for a different pending comic', async () => {
  const previousKey = 'roll-offer-0123456789abcdef0123456789abcdef'
  globalThis.sessionStorage?.setItem(
    'comicpile:roll:pending-offer',
    JSON.stringify({ key: previousKey, expectedPendingThreadId: 42 }),
  )
  client.post.mockRejectedValueOnce(new Error('connection dropped')).mockResolvedValueOnce({})

  const isolated = createRollApi(client)
  await expect(isolated.reroll(42)).rejects.toThrow('connection dropped')
  await isolated.reroll(43)

  expect(client.post).toHaveBeenNthCalledWith(
    2,
    '/v2/roll/offer',
    expect.objectContaining({ expected_pending_thread_id: 43 }),
  )
  expect(client.post).not.toHaveBeenNthCalledWith(
    2,
    '/v2/roll/offer',
    expect.objectContaining({ idempotency_key: previousKey }),
  )
})

it('discards a pending offer key whose stored thread intent is malformed', async () => {
  const previousKey = 'roll-offer-0123456789abcdef0123456789abcdef'
  globalThis.sessionStorage?.setItem(
    'comicpile:roll:pending-offer',
    JSON.stringify({ key: previousKey, expectedPendingThreadId: '42' }),
  )

  const isolated = createRollApi(client)
  await isolated.reroll(42)

  expect(client.post).not.toHaveBeenCalledWith(
    '/v2/roll/offer',
    expect.objectContaining({ idempotency_key: previousKey }),
  )
})

