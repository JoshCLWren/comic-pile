import { describe, expect, it } from 'vitest'
import {
  buildPayload,
  errorMessage,
  getConflictMessage,
  laneNodeCount,
  normalizePositions,
  type PlannerNode,
} from '../pages/continuity-planner/plannerModel'

function node(overrides: Partial<PlannerNode> & { id: string }): PlannerNode {
  return {
    node_type: 'issue',
    ref_id: 1,
    lane_id: 'main',
    position: 0,
    label: overrides.id,
    ...overrides,
  }
}

describe('normalizePositions', () => {
  it('reassigns contiguous positions per lane while preserving order', () => {
    const result = normalizePositions([
      node({ id: 'a', lane_id: 'main', position: 5 }),
      node({ id: 'b', lane_id: 'main', position: 2 }),
      node({ id: 'c', lane_id: 'other', position: 9 }),
    ])
    expect(result).toEqual([
      expect.objectContaining({ id: 'b', position: 0 }),
      expect.objectContaining({ id: 'a', position: 1 }),
      expect.objectContaining({ id: 'c', lane_id: 'other', position: 0 }),
    ])
  })
})

describe('laneNodeCount', () => {
  it('counts only nodes in the requested lane', () => {
    const nodes = [node({ id: 'a' }), node({ id: 'b', lane_id: 'other' })]
    expect(laneNodeCount(nodes, 'main')).toBe(1)
    expect(laneNodeCount(nodes, 'missing')).toBe(0)
  })
})

describe('buildPayload', () => {
  it('trims the name, orders lanes, and fills node defaults', () => {
    const payload = buildPayload(
      '  Kirby lane  ',
      [
        { id: 'b', name: 'Second', order: 1 },
        { id: 'a', name: 'First', order: 0 },
      ],
      [node({ id: 'n1', lane_id: 'b', position: 3 })],
      'informational',
    )
    expect(payload.name).toBe('Kirby lane')
    expect(payload.ordering_mode).toBe('informational')
    expect(payload.lanes.map((lane) => lane.id)).toEqual(['a', 'b'])
    expect(payload.nodes).toEqual([
      expect.objectContaining({
        id: 'n1',
        lane_id: 'b',
        position: 0,
        is_checkpoint: false,
        convergence_gate: [],
      }),
    ])
  })
})

describe('errorMessage', () => {
  it('prefers the API detail string from axios errors', () => {
    const error = { isAxiosError: true, response: { data: { detail: 'Nope.' } } }
    expect(errorMessage(error, 'Fallback')).toBe('Nope.')
  })

  it('falls back to the Error message and then the fallback', () => {
    expect(errorMessage(new Error('Boom'), 'Fallback')).toBe('Boom')
    expect(errorMessage(null, 'Fallback')).toBe('Fallback')
  })
})

describe('getConflictMessage', () => {
  const nodes = [node({ id: 's', label: 'Alpha' }), node({ id: 't', label: 'Omega' })]

  function axiosError(detail: unknown) {
    return { isAxiosError: true, response: { data: { detail } } }
  }

  it('returns plain Error messages for non-axios failures', () => {
    expect(getConflictMessage(new Error('Boom'), nodes)).toBe('Boom')
  })

  it('prefers the API detail string when present', () => {
    expect(getConflictMessage(axiosError('Custom detail'), nodes)).toBe('Custom detail')
  })

  it('names both steps for a rule conflict between known nodes', () => {
    const message = getConflictMessage(
      axiosError({ code: 'plan_rule_conflict', source_node_id: 's', target_node_id: 't' }),
      nodes,
    )
    expect(message).toContain('"Alpha"')
    expect(message).toContain('"Omega"')
  })

  it('names both steps for a cycle between known nodes', () => {
    const message = getConflictMessage(
      axiosError({ code: 'continuity_cycle', source_node_id: 's', target_node_id: 't' }),
      nodes,
    )
    expect(message).toContain('continuity cycle')
    expect(message).toContain('"Alpha"')
  })

  it('falls back to generic guidance when node ids are unknown', () => {
    expect(
      getConflictMessage(
        axiosError({ code: 'plan_rule_conflict', source_node_id: 'x', target_node_id: 'y' }),
        nodes,
      ),
    ).toContain('continuity rule')
    expect(
      getConflictMessage(
        axiosError({ code: 'continuity_cycle', source_node_id: 'x', target_node_id: 'y' }),
        nodes,
      ),
    ).toContain('continuity cycle')
  })

  it('falls back to the generic message for unrecognized payloads', () => {
    expect(getConflictMessage(axiosError({ nope: true }), nodes)).toBe(
      'Unable to save this continuity plan.',
    )
    expect(getConflictMessage(axiosError({ code: 'something-else' }), nodes)).toBe(
      'Unable to save this continuity plan.',
    )
  })
})
