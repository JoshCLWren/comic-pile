import { beforeEach, expect, it } from 'vitest'
import { createRateApi } from '../services/api-rate'
import { createRollApi } from '../services/api-roll'
import { createProtectedRollMutationApi } from '../services/protectedRollMutationApi'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const rateApi = createRateApi(client)
const rollApi = createRollApi(client)
const protectedRollMutationApi = createProtectedRollMutationApi(client)
const rollBootstrapApi = createRollBootstrapApi(client)

beforeEach(() => {
  globalThis.sessionStorage?.removeItem('comicpile:roll:pending-manual-die')
  globalThis.sessionStorage?.removeItem('comicpile:roll:pending-offer')
  globalThis.document.cookie = 'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  client.get.mockReset().mockResolvedValue({ rollable: [], total_threads: 0, available_threads: 0, excluded_count: 0, excluded_threads: [], inactive_count: 0, inactive_threads: [] })
  client.post.mockReset().mockResolvedValue({})
})

it('calls Rust v2 offer for Roll/Reroll while composite mutations remain on v1', async () => {
  await rollApi.roll()
  await rollApi.reroll()
  await rollApi.override({ thread_id: 7 })
  await rollApi.dismissPending()
  await rollApi.setDie(12)
  await rollApi.clearManualDie()
  await rateApi.rate({ thread_id: 7, rating: 4 })
  await rollBootstrapApi.get()

  expect(client.post).toHaveBeenCalledWith(
    '/v2/roll/offer',
    expect.objectContaining({
      snoozed_thread_ids: [],
      idempotency_key: expect.stringMatching(/^roll-offer-[0-9a-f]{32}$/),
    }),
  )
  expect(client.post).toHaveBeenCalledWith('/v1/roll/override', { thread_id: 7 })
  expect(client.post).toHaveBeenCalledWith('/v1/roll/dismiss-pending')
  expect(client.post).toHaveBeenCalledWith('/v2/roll/dice-command', {
    kind: 'manual_select',
    die: 12,
    idempotency_key: expect.stringMatching(/^roll-[0-9a-f]{32}$/),
  })
  expect(client.post).toHaveBeenCalledWith('/v1/roll/clear-manual-die')
  expect(client.post).toHaveBeenCalledWith('/v1/rate/', {
    thread_id: 7,
    rating: 4,
  })
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})

it('reads native v2 during auth recovery while keeping mutations on v1', async () => {
  await protectedRollMutationApi.rate({ thread_id: 9, rating: 3 })
  await protectedRollMutationApi.bootstrap()
  await protectedRollMutationApi.snooze()

  expect(client.post).toHaveBeenCalledWith(
    '/v1/rate/',
    { thread_id: 9, rating: 3 },
    { skipAuthRedirect: true },
  )
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap', { skipAuthRedirect: true })
  expect(client.post).toHaveBeenCalledWith('/v1/snooze/', undefined, { skipAuthRedirect: true })
})

it('reuses an unanswered command key, but not a confirmed command key', async () => {
  const isolated = createRollApi(client)
  client.post.mockRejectedValueOnce(new Error('network response lost'))

  await expect(isolated.setDie(8)).rejects.toThrow('network response lost')
  await isolated.setDie(8)
  await isolated.setDie(8)
  await isolated.setDie(12)

  // SAFETY: this isolated test invokes only setDie, which always posts a ManualDieCommand payload.
  const commands = client.post.mock.calls.map((args) => args[1] as { idempotency_key: string; die: number })
  expect(commands.map((command) => command.die)).toEqual([8, 8, 8, 12])
  expect(commands[1].idempotency_key).toBe(commands[0].idempotency_key)
  expect(commands[2].idempotency_key).not.toBe(commands[1].idempotency_key)
  expect(commands[3].idempotency_key).not.toBe(commands[2].idempotency_key)
})

it('survives a browser refresh without duplicating an unacknowledged manual die event', async () => {
  const firstPage = createRollApi(client)
  client.post.mockRejectedValueOnce(new Error('connection dropped'))
  await expect(firstPage.setDie(4)).rejects.toThrow('connection dropped')

  // A new service instance models a page refresh in the same browser tab.
  const afterRefresh = createRollApi(client)
  await afterRefresh.setDie(4)
  const commands = client.post.mock.calls
  expect(commands[1][1]).toEqual(commands[0][1])
  expect(globalThis.sessionStorage?.getItem('comicpile:roll:pending-manual-die')).toBeNull()
})

it('reuses an unanswered Roll offer key across refresh, then clears it', async () => {
  const firstPage = createRollApi(client)
  client.post.mockRejectedValueOnce(new Error('connection dropped'))
  await expect(firstPage.roll()).rejects.toThrow('connection dropped')

  // A new service instance models a page refresh in the same browser tab.
  const afterRefresh = createRollApi(client)
  client.post.mockResolvedValueOnce({ thread_id: 4, result: 2, die_size: 6 })
  await afterRefresh.roll()

  // SAFETY: this test invokes only offer, which always posts a RollOfferPayload.
  const payloads = client.post.mock.calls.map(
    (args) => args[1] as { idempotency_key: string; snoozed_thread_ids: number[] },
  )
  expect(payloads[1].idempotency_key).toBe(payloads[0].idempotency_key)
  expect(globalThis.sessionStorage?.getItem('comicpile:roll:pending-offer')).toBeNull()
})

it('records the snoozed thread in a bounded midnight cookie', async () => {
  client.post.mockResolvedValueOnce({ thread_id: 4, result: 2, snoozed_thread_id: 9 })
  await rollApi.roll()

  const cookie = globalThis.document.cookie
    .split('; ')
    .find((entry) => entry.startsWith('comicpile_roll_snoozes='))
  expect(cookie).toBeDefined()
  const encoded = cookie?.slice('comicpile_roll_snoozes='.length) ?? ''
  expect(JSON.parse(decodeURIComponent(encoded))).toEqual([9])

  client.post.mockResolvedValueOnce({ thread_id: 5, result: 1 })
  await rollApi.roll()
  const nextCookie = globalThis.document.cookie
    .split('; ')
    .find((entry) => entry.startsWith('comicpile_roll_snoozes='))
  const nextEncoded = nextCookie?.slice('comicpile_roll_snoozes='.length) ?? ''
  expect(JSON.parse(decodeURIComponent(nextEncoded))).toEqual([9])
  // SAFETY: this test invokes only offer, which always posts a RollOfferPayload.
  const payload = client.post.mock.calls.at(-1)?.[1] as { snoozed_thread_ids: number[] }
  expect(payload.snoozed_thread_ids).toEqual([9])
})

it('resets dice through Rust and clears temporary snoozes', async () => {
  globalThis.document.cookie = `comicpile_roll_snoozes=${encodeURIComponent('[9]')}`
  client.post.mockResolvedValueOnce({ die: 6, replayed: false })

  const result = await rollApi.reset()

  expect(result).toEqual({ die: 6, replayed: false })
  expect(client.post).toHaveBeenCalledWith('/v2/roll/reset', {
    idempotency_key: expect.stringMatching(/^roll-[0-9a-f]{32}$/),
  })
  const cookie = globalThis.document.cookie
    .split('; ')
    .find((entry) => entry.startsWith('comicpile_roll_snoozes='))
  const encoded = cookie?.slice('comicpile_roll_snoozes='.length) ?? ''
  expect(JSON.parse(decodeURIComponent(encoded))).toEqual([])
})
