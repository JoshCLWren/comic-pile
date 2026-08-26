import { beforeEach, expect, it, vi } from 'vitest'

import type { ContinuityPlan } from '../services/api-continuity-plans'
import type { InsertReadingOrderItemResponse } from '../services/api-reading-orders'
import { readingOrdersApi } from '../services/api-reading-orders'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('axios', () => ({
  default: { create: vi.fn(() => ({
    get: apiMock.get,
    post: apiMock.post,
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  })) },
}))

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

it('inserts an item at a position within a reading order', async () => {
  const response: InsertReadingOrderItemResponse = {
    reading_order_id: 1,
    thread_id: 7,
    position: 3,
    total_items: 5,
  }
  apiMock.post.mockResolvedValue(response)

  const result = await readingOrdersApi.insertItem(1, { thread_id: 7, position: 3 })

  expect(result).toEqual(response)
  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/reading-orders/1/items',
    { thread_id: 7, position: 3 },
  )
})

it('adopts a legacy reading order into a canonical plan with all optional overrides', async () => {
  const plan: ContinuityPlan = {
    id: 42,
    name: 'Custom Plan',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'primary', name: 'Primary', order: 0 }],
    nodes: [],
    user_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
  apiMock.post.mockResolvedValue(plan)

  const result = await readingOrdersApi.adoptReadingOrder({
    readingOrderId: 5,
    planName: 'Custom Plan',
    laneId: 'primary',
    laneName: 'Primary',
  })

  expect(result).toEqual(plan)
  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/continuity-plans/from-reading-order',
    {
      reading_order_id: 5,
      plan_name: 'Custom Plan',
      lane_id: 'primary',
      lane_name: 'Primary',
    },
  )
})

it('adopts a reading order using schema defaults when optional fields are omitted', async () => {
  const plan: ContinuityPlan = {
    id: 43,
    name: 'My Legacy Order',
    ordering_mode: 'informational',
    lanes: [{ id: 'adopted', name: 'Adopted', order: 0 }],
    nodes: [],
    user_id: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
  apiMock.post.mockResolvedValue(plan)

  const result = await readingOrdersApi.adoptReadingOrder({ readingOrderId: 9 })

  expect(result).toEqual(plan)
  expect(apiMock.post).toHaveBeenCalledWith(
    '/v1/continuity-plans/from-reading-order',
    {
      reading_order_id: 9,
      plan_name: null,
      lane_id: 'adopted',
      lane_name: 'Adopted',
    },
  )
})