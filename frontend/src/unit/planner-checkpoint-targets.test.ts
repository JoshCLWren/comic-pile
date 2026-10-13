import { describe, expect, it } from 'vitest'

import { buildPayload, type PlannerNode } from '../pages/continuity-planner/plannerModel'

describe('planner checkpoint serialization', () => {
  it('preserves both singular and fan-out targets when saved or reordered', () => {
    const source: PlannerNode = {
      id: 'source', node_type: 'issue', ref_id: 1, lane_id: 'main', position: 0,
      label: 'Source', is_checkpoint: true,
      checkpoint_target_ref_id: 3, checkpoint_target_ref_ids: [3, 4],
    }
    const saved = buildPayload('Order', [{ id: 'main', name: 'Main', order: 0 }], [source], 'strict_sequential')
    expect(saved.nodes[0].checkpoint_target_ref_id).toBe(3)
    expect(saved.nodes[0].checkpoint_target_ref_ids).toEqual([3, 4])
  })

  it('clears target metadata when the reader disables the checkpoint', () => {
    const source: PlannerNode = {
      id: 'source', node_type: 'issue', ref_id: 1, lane_id: 'main', position: 0,
      label: 'Source', is_checkpoint: false,
      checkpoint_target_ref_id: 3, checkpoint_target_ref_ids: [3, 4],
    }
    const saved = buildPayload('Order', [{ id: 'main', name: 'Main', order: 0 }], [source], 'strict_sequential')
    expect(saved.nodes[0].checkpoint_target_ref_id).toBeNull()
    expect(saved.nodes[0].checkpoint_target_ref_ids).toEqual([])
  })
})
