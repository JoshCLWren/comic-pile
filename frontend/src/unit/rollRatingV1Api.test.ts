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
  client.get.mockReset().mockResolvedValue({ rollable: [], total_threads: 0, available_threads: 0, excluded_count: 0, excluded_threads: [], inactive_count: 0, inactive_threads: [] })
  client.post.mockReset().mockResolvedValue({})
})

it('uses native v2 only for bootstrap while keeping other Roll mutations on v1', async () => {
  // The clear-die endpoint answers with a plain-text die label, so the stub
  // returns that shape for the canonical-path assertions below.
  client.post.mockResolvedValue('d6')
  await rollApi.roll()
  await rollApi.reroll()
  await rollApi.override({ thread_id: 7 })
  await rollApi.dismissPending()
  await rollApi.setDie(12)
  await rollApi.clearManualDie()
  await rateApi.rate({ thread_id: 7, rating: 4 })
  await rollBootstrapApi.get()

  expect(client.post).toHaveBeenCalledWith('/v1/roll/')
  expect(client.post).toHaveBeenCalledWith('/v1/roll/override', { thread_id: 7 })
  expect(client.post).toHaveBeenCalledWith('/v1/roll/dismiss-pending')
  expect(client.post).toHaveBeenCalledWith('/v1/roll/set-die', null, { params: { die: 12 } })
  expect(client.post).toHaveBeenCalledWith('/v1/roll/clear-manual-die', undefined, {
    responseType: 'text',
  })
  expect(client.post).toHaveBeenCalledWith('/v1/rate/', {
    thread_id: 7,
    rating: 4,
  })
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})

it('reads the automatic die that clear-manual-die reports (#4279)', async () => {
  client.post.mockResolvedValueOnce('d8')

  await expect(rollApi.clearManualDie()).resolves.toBe(8)
})

it('reports no die when the clear-manual-die body is not a die label', async () => {
  client.post.mockResolvedValueOnce('ok')

  await expect(rollApi.clearManualDie()).resolves.toBeNull()
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
