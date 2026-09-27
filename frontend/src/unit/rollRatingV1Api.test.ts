import { beforeEach, expect, it, vi } from 'vitest'
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
  client.get.mockReset().mockResolvedValue({})
  client.post.mockReset().mockResolvedValue({})
})

it('uses canonical v1 Roll and rating paths for maintained callers', async () => {
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
  expect(client.post).toHaveBeenCalledWith('/v1/roll/clear-manual-die')
  expect(client.post).toHaveBeenCalledWith('/v1/rate/', {
    thread_id: 7,
    rating: 4,
  })
  expect(client.get).toHaveBeenCalledWith('/v1/roll/bootstrap')
})

it('keeps auth-recovery Roll mutations on canonical v1 paths', async () => {
  await protectedRollMutationApi.rate({ thread_id: 9, rating: 3 })
  await protectedRollMutationApi.bootstrap()
  await protectedRollMutationApi.snooze()

  expect(client.post).toHaveBeenCalledWith(
    '/v1/rate/',
    { thread_id: 9, rating: 3 },
    { skipAuthRedirect: true },
  )
  expect(client.get).toHaveBeenCalledWith('/v1/roll/bootstrap', { skipAuthRedirect: true })
  expect(client.post).toHaveBeenCalledWith('/v1/snooze/', undefined, { skipAuthRedirect: true })
})
