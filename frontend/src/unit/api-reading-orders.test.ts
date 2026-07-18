import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('axios', () => ({
  default: { create: vi.fn(() => ({
    get: apiMock.get,
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  })) },
}))

import { readingOrdersApi } from '../services/api-reading-orders'

beforeEach(() => {
  apiMock.get.mockReset()
})

it('uses the shared API client so expired tokens can be refreshed and retried', async () => {
  apiMock.get.mockResolvedValue({ reading_orders: [] })

  await expect(readingOrdersApi.getForThread(42)).resolves.toEqual({ reading_orders: [] })

  expect(apiMock.get).toHaveBeenCalledWith('/v1/threads/42/reading-orders')
})

it('propagates errors from the shared API client', async () => {
  apiMock.get.mockRejectedValue(new Error('Unauthorized'))

  await expect(readingOrdersApi.getForThread(42)).rejects.toThrow('Unauthorized')
})
