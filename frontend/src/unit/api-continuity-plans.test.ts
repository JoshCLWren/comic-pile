import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      get: apiMock.get,
      post: apiMock.post,
      put: apiMock.put,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    })),
  },
}))

import { continuityPlansApi, type ContinuityPlanWrite } from '../services/api-continuity-plans'

const payload: ContinuityPlanWrite = {
  name: 'Kirby lane',
  ordering_mode: 'strict_sequential',
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [],
}

describe('continuityPlansApi', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.put.mockReset()
  })

  it('uses the shared API client so expired tokens can be refreshed and retried', async () => {
    apiMock.post.mockResolvedValue({ id: 12, ...payload, user_id: 1, created_at: '', updated_at: '' })

    await expect(continuityPlansApi.create(payload)).resolves.toEqual(
      expect.objectContaining({ id: 12 }),
    )

    expect(apiMock.post).toHaveBeenCalledWith('/v1/continuity-plans/', payload)
  })

  it('fetches a single plan by id', async () => {
    apiMock.get.mockResolvedValue({ id: 12, ...payload, user_id: 1, created_at: '', updated_at: '' })

    await expect(continuityPlansApi.get(12)).resolves.toEqual(
      expect.objectContaining({ id: 12 }),
    )

    expect(apiMock.get).toHaveBeenCalledWith('/v1/continuity-plans/12')
  })

  it('updates a plan by id', async () => {
    apiMock.put.mockResolvedValue({ id: 12, ...payload, user_id: 1, created_at: '', updated_at: '' })

    await expect(continuityPlansApi.update(12, payload)).resolves.toEqual(
      expect.objectContaining({ id: 12 }),
    )

    expect(apiMock.put).toHaveBeenCalledWith('/v1/continuity-plans/12', payload)
  })

  it('propagates errors from the shared API client', async () => {
    apiMock.post.mockRejectedValue(new Error('Unauthorized'))

    await expect(continuityPlansApi.create(payload)).rejects.toThrow('Unauthorized')
  })
})
