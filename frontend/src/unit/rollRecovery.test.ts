import { describe, expect, it } from 'vitest'
import { parseRollRecovery } from '../services/rollRecovery'

const CANONICAL_RECOVERY = {
  original_thread_id: 3,
  original_thread_title: 'Current Series',
  direct_blockers: [{
    rule_id: null,
    source_type: 'issue',
    source_id: 20,
    source_label: 'Middle Series #2',
    satisfaction_type: 'item_read',
    satisfied: false,
    causing_issue_ids: [20],
    causing_member_issue_ids: [],
    note: 'reader',
  }],
  readable_prerequisites: [
    { node_type: 'issue', node_id: 20, label: 'Middle Series #2', is_readable: false },
    { node_type: 'issue', node_id: 30, label: 'Earlier Series #1', is_readable: true },
  ],
  chains: [[
    { node_type: 'issue', node_id: 3, label: 'Current Series #1', is_readable: false },
    { node_type: 'issue', node_id: 20, label: 'Middle Series #2', is_readable: false },
    { node_type: 'issue', node_id: 30, label: 'Earlier Series #1', is_readable: true },
  ]],
  diagnostics: [],
}

describe('canonical scoped Roll recovery wire boundary', () => {
  it('preserves transitive chains and readable leaves from the canonical graph', () => {
    const recovery = parseRollRecovery(CANONICAL_RECOVERY)

    expect(recovery?.direct_blockers[0]).toMatchObject({
      source_id: 20,
      source_label: 'Middle Series #2',
      satisfied: false,
    })
    expect(recovery?.readable_prerequisites).toEqual([
      { node_type: 'issue', node_id: 20, label: 'Middle Series #2', is_readable: false },
      { node_type: 'issue', node_id: 30, label: 'Earlier Series #1', is_readable: true },
    ])
    expect(recovery?.chains[0].map((node) => node.node_id)).toEqual([3, 20, 30])
  })

  it('preserves bounded cycle, depth, and node-limit diagnostics', () => {
    const recovery = parseRollRecovery({
      ...CANONICAL_RECOVERY,
      diagnostics: [
        { code: 'cycle_detected', node_type: 'issue', node_id: 20, limit: null },
        { code: 'depth_limit_exceeded', node_type: 'issue', node_id: 30, limit: 32 },
        { code: 'node_limit_exceeded', node_type: 'issue', node_id: 3, limit: 500 },
      ],
    })

    expect(recovery?.diagnostics).toEqual([
      { code: 'cycle_detected', node_type: 'issue', node_id: 20, limit: undefined },
      { code: 'depth_limit_exceeded', node_type: 'issue', node_id: 30, limit: 32 },
      { code: 'node_limit_exceeded', node_type: 'issue', node_id: 3, limit: 500 },
    ])
  })

  it('fails closed on malformed or foreign node shapes', () => {
    expect(parseRollRecovery(null)).toBeNull()
    expect(parseRollRecovery({ ...CANONICAL_RECOVERY, original_thread_id: 0 })).toBeNull()
    expect(parseRollRecovery({
      ...CANONICAL_RECOVERY,
      direct_blockers: [{ ...CANONICAL_RECOVERY.direct_blockers[0], source_type: 'thread' }],
    })).toBeNull()
    expect(parseRollRecovery({
      ...CANONICAL_RECOVERY,
      readable_prerequisites: [{ node_type: 'issue', node_id: -1, label: 'Foreign' }],
    })).toBeNull()
  })
})
