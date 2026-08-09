import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  request: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { rateApi, rollApi } from '../services/api'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({})
  apiMock.post.mockReset().mockResolvedValue({})
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

  expect(apiMock.post).toHaveBeenCalledWith('/v1/roll/')
  expect(apiMock.post).toHaveBeenCalledWith('/v1/roll/override', { thread_id: 7 })
  expect(apiMock.post).toHaveBeenCalledWith('/v1/roll/dismiss-pending')
  expect(apiMock.post).toHaveBeenCalledWith('/v1/roll/set-die', null, { params: { die: 12 } })
  expect(apiMock.post).toHaveBeenCalledWith('/v1/roll/clear-manual-die')
  expect(apiMock.post).toHaveBeenCalledWith('/v1/rate/', {
    thread_id: 7,
    rating: 4,
  })
  expect(apiMock.get).toHaveBeenCalledWith('/v1/roll/bootstrap')
})

it('keeps auth-recovery Roll mutations on v1 while snooze remains on its own migration track', async () => {
  await protectedRollMutationApi.rate({ thread_id: 9, rating: 3 })
  await protectedRollMutationApi.bootstrap()
  await protectedRollMutationApi.snooze()

  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/rate/',
    { thread_id: 9, rating: 3 },
    { skipAuthRedirect: true },
  )
  expect(apiMock.get).toHaveBeenCalledWith('/v1/roll/bootstrap', { skipAuthRedirect: true })
  expect(apiMock.post).toHaveBeenCalledWith('/snooze/', undefined, { skipAuthRedirect: true })
})
