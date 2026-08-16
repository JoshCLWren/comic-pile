import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('axios', () => ({
  default: { create: vi.fn(() => ({
    get: apiMock.get,
    post: apiMock.post,
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  })) },
}))

import { readingOrdersApi } from '../services/api-reading-orders'

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
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

it('lists reading orders through the shared API client', async () => {
  apiMock.get.mockResolvedValue({ reading_orders: [{ id: 1, name: 'Alpha', description: null, total_items: 0 }] })

  await expect(readingOrdersApi.list()).resolves.toEqual({
    reading_orders: [{ id: 1, name: 'Alpha', description: null, total_items: 0 }],
  })

  expect(apiMock.get).toHaveBeenCalledWith('/v1/reading-orders/')
})

it('previews a projection with the plan id and selected reading order', async () => {
  apiMock.post.mockResolvedValue({ plan_id: 9, reading_order_id: 3, entries: [], conflicts: [], total_positions: 0, plan_name: 'Plan', plan_ordering_mode: 'strict_sequential', reading_order_name: 'Order', dropped_node_ids: [] })

  await expect(readingOrdersApi.previewProjection(9, 3)).resolves.toMatchObject({ plan_id: 9, reading_order_id: 3 })

  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/continuity-plans/9/reading-orders/project-preview',
    { reading_order_id: 3 },
  )
})

it('confirms a projection with the plan id and selected reading order', async () => {
  apiMock.post.mockResolvedValue({ plan_id: 9, reading_order_id: 3, added_count: 2, updated_count: 0, kept_count: 0, total_positions: 2 })

  await expect(readingOrdersApi.confirmProjection(9, 3)).resolves.toMatchObject({ plan_id: 9, added_count: 2 })

  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/continuity-plans/9/reading-orders/project',
    { reading_order_id: 3 },
  )
})
