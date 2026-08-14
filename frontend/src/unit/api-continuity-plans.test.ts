import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('../services/api', () => ({
  default: apiMock,
}))

import { continuityPlansApi } from '../services/api-continuity-plans'

const basePlan = {
  id: 12,
  user_id: 1,
  name: 'Kirby lane',
  ordering_mode: 'strict_sequential' as const,
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [
    { id: 'issue-40', node_type: 'issue' as const, ref_id: 40, lane_id: 'main', position: 0 },
    { id: 'crossover-8', node_type: 'crossover' as const, ref_id: 8, lane_id: 'main', position: 1 },
  ],
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.put.mockReset()
  apiMock.delete.mockReset()
})

describe('continuityPlansApi', () => {
  it('creates a strict-sequential plan', async () => {
    apiMock.post.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.create({
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })).resolves.toEqual(basePlan)

    expect(apiMock.post).toHaveBeenCalledWith('/v1/continuity-plans/', {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })
  })

  it('loads a plan by id', async () => {
    apiMock.get.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.get(12)).resolves.toEqual(basePlan)

    expect(apiMock.get).toHaveBeenCalledWith('/v1/continuity-plans/12')
  })

  it('replaces a plan with a full ordered payload', async () => {
    apiMock.put.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.update(12, {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })).resolves.toEqual(basePlan)

    expect(apiMock.put).toHaveBeenCalledWith('/v1/continuity-plans/12', {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })
  })
})
