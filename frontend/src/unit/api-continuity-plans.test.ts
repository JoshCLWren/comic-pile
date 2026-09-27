import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createContinuityPlansApi } from '../services/api-continuity-plans'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const continuityPlansApi = createContinuityPlansApi(client)

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
  client.get.mockReset()
  client.post.mockReset()
  client.put.mockReset()
  client.delete.mockReset()
})

describe('continuityPlansApi', () => {
  it('creates a strict-sequential plan', async () => {
    client.post.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.create({
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })).resolves.toEqual(basePlan)

    expect(client.post).toHaveBeenCalledWith('/v1/continuity-plans/', {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })
  })

  it('loads a plan by id', async () => {
    client.get.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.get(12)).resolves.toEqual(basePlan)

    expect(client.get).toHaveBeenCalledWith('/v1/continuity-plans/12')
  })

  it('replaces a plan with a full ordered payload', async () => {
    client.put.mockResolvedValueOnce(basePlan)

    await expect(continuityPlansApi.update(12, {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })).resolves.toEqual(basePlan)

    expect(client.put).toHaveBeenCalledWith('/v1/continuity-plans/12', {
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: basePlan.lanes,
      nodes: basePlan.nodes,
    })
  })

  it('creates a parallel-lane informational plan', async () => {
    const parallelPlan = {
      ...basePlan,
      ordering_mode: 'informational' as const,
      lanes: [
        { id: 'era-a', name: 'Era A', order: 0 },
        { id: 'era-b', name: 'Era B', order: 1 },
      ],
      nodes: [
        { id: 'a-40', node_type: 'issue' as const, ref_id: 40, lane_id: 'era-a', position: 0 },
        { id: 'b-8', node_type: 'crossover' as const, ref_id: 8, lane_id: 'era-b', position: 0 },
      ],
    }
    client.post.mockResolvedValueOnce(parallelPlan)

    await expect(continuityPlansApi.create({
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: parallelPlan.lanes,
      nodes: parallelPlan.nodes,
    })).resolves.toEqual(parallelPlan)

    expect(client.post).toHaveBeenCalledWith('/v1/continuity-plans/', {
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: parallelPlan.lanes,
      nodes: parallelPlan.nodes,
    })
  })
})
