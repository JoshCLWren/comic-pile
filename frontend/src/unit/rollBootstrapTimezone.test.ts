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

import { rollBootstrapApi } from '../services/rollBootstrapApi'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({})
})

it('sends a valid browser IANA timezone as the bootstrap query parameter', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(apiMock.get).toHaveBeenCalledWith('/v1/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
})

it('keeps the canonical bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(apiMock.get).toHaveBeenCalledWith('/v1/roll/bootstrap')
  expect(apiMock.get).toHaveBeenCalledTimes(1)
})

it('treats a blank timezone like a missing value instead of sending garbage', async () => {
  await rollBootstrapApi.get('')

  expect(apiMock.get).toHaveBeenCalledWith('/v1/roll/bootstrap')
})
