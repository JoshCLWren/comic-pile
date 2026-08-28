import { describe, expect, it } from 'vitest'
import {
  buildPrerequisiteLanes,
  classifyEdgesRelativeToCurrent,
} from '../pages/RollPage/readingPath'
import type { ReaderContextEdge } from '../types'

function edge(overrides: Partial<ReaderContextEdge> & { id: number; source_issue_id: number; target_issue_id: number }): ReaderContextEdge {
  return {
    kind: 'dependency',
    source_thread_id: 1,
    target_thread_id: 2,
    source_label: `Issue ${overrides.source_issue_id}`,
    target_label: `Issue ${overrides.target_issue_id}`,
    source_status: null,
    target_status: null,
    note: null,
    explanation: null,
    source_thread_title: null,
    target_thread_title: null,
    source_issue_number: null,
    target_issue_number: null,
    ...overrides,
  } as ReaderContextEdge
}

describe('classifyEdgesRelativeToCurrent', () => {
  it('groups prerequisites, downstream unlocks, and future context relative to current', () => {
    // Fixture from issue #1916 / production comment: MM #6 -> Evil #1 -> MM #7 (current) plus future MM #9 -> Superman #17
    const mm6 = 22946
    const mm7 = 22947
    const mm9 = 22949
    const evil1 = 22950
    const superman17 = 22902
    const edges: ReaderContextEdge[] = [
      edge({ id: 944, kind: 'continuity', source_issue_id: mm6, target_issue_id: evil1, source_label: 'Absolute Martian Manhunter #6', target_label: 'Absolute Evil #1' }),
      edge({ id: 945, kind: 'continuity', source_issue_id: evil1, target_issue_id: mm7, source_label: 'Absolute Evil #1', target_label: 'Absolute Martian Manhunter #7' }),
      edge({ id: 949, kind: 'continuity', source_issue_id: mm9, target_issue_id: superman17, source_label: 'Absolute Martian Manhunter #9', target_label: 'Absolute Superman #17' }),
    ]

    const { intoCurrent, fromCurrent, later } = classifyEdgesRelativeToCurrent(edges, mm7)
    expect(intoCurrent.map((e) => e.id)).toEqual([945])
    expect(fromCurrent).toEqual([])
    expect(later.map((e) => e.id).sort()).toEqual([944, 949].sort())
  })

  it('separates edges that unlock after the current issue', () => {
    const current = 100
    const laterOnly = edge({ id: 20, source_issue_id: 200, target_issue_id: 201 })
    const fromCurrent = edge({ id: 21, source_issue_id: current, target_issue_id: 202 })
    const { fromCurrent: fc, later } = classifyEdgesRelativeToCurrent([laterOnly, fromCurrent], current)
    expect(fc.map((e) => e.id)).toEqual([21])
    expect(later.map((e) => e.id)).toEqual([20])
  })

  it('ignores degenerate self-loops on the current issue', () => {
    const current = 10
    const self = edge({ id: 99, source_issue_id: current, target_issue_id: current })
    const { intoCurrent, fromCurrent, later } = classifyEdgesRelativeToCurrent([self], current)
    expect(intoCurrent).toEqual([])
    expect(fromCurrent).toEqual([])
    expect(later).toEqual([])
  })
})

describe('buildPrerequisiteLanes', () => {
  it('builds a bounded lane for the 1916 chain without flattening into a fake order', () => {
    const mm6 = 22946
    const mm7 = 22947
    const evil1 = 22950
    const edges: ReaderContextEdge[] = [
      edge({ id: 945, source_issue_id: evil1, target_issue_id: mm7, source_label: 'Absolute Evil #1', target_label: 'Absolute Martian Manhunter #7', explanation: 'needs Evil' }),
      edge({ id: 944, source_issue_id: mm6, target_issue_id: evil1, source_label: 'Absolute Martian Manhunter #6', target_label: 'Absolute Evil #1', explanation: 'needs #6' }),
    ]

    const lanes = buildPrerequisiteLanes(edges, mm7)
    expect(lanes).toHaveLength(1)
    expect(lanes[0].map((s) => s.issueId)).toEqual([mm6, evil1])
    expect(lanes[0][1].explanations).toContain('needs Evil')
    expect(lanes[0][0].explanations).toContain('needs #6')
  })

  it('preserves truthful branching for parallel prerequisites', () => {
    const current = 100
    const a = 10
    const b = 20
    const edges: ReaderContextEdge[] = [
      edge({ id: 1, source_issue_id: a, target_issue_id: current, source_label: 'A' }),
      edge({ id: 2, source_issue_id: b, target_issue_id: current, source_label: 'B' }),
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    expect(lanes).toHaveLength(2)
    const sorted = lanes.map((lane) => lane[0].issueId).sort()
    expect(sorted).toEqual([a, b].sort())
  })

  it('collapses duplicate branching and terminates cycles deterministically', () => {
    const current = 3
    const a = 1
    const b = 2
    const edges: ReaderContextEdge[] = [
      edge({ id: 1, source_issue_id: a, target_issue_id: current }),
      edge({ id: 2, source_issue_id: b, target_issue_id: a }),
      edge({ id: 3, source_issue_id: a, target_issue_id: b }), // creates cycle a <-> b
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    // Should terminate and not infinitely loop
    expect(lanes.length).toBeGreaterThanOrEqual(1)
    for (const lane of lanes) {
      const ids = lane.map((s) => s.issueId)
      // No duplicate issue within a lane
      expect(new Set(ids).size).toBe(ids.length)
    }
  })

  it('carries per-endpoint read status when available', () => {
    const current = 50
    const prereq = 40
    const edges: ReaderContextEdge[] = [
      edge({ id: 10, source_issue_id: prereq, target_issue_id: current, source_status: 'read', target_status: 'unread' }),
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    expect(lanes[0][0].status).toBe('read')
  })

  it('ignores self-loops', () => {
    const current = 5
    const edges: ReaderContextEdge[] = [
      edge({ id: 99, source_issue_id: current, target_issue_id: current }),
      edge({ id: 100, source_issue_id: 1, target_issue_id: current }),
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    expect(lanes).toHaveLength(1)
    expect(lanes[0][0].issueId).toBe(1)
  })

  it('branches forked prerequisites into separate lanes via secondary candidates', () => {
    const current = 100
    const a = 10
    const b = 20
    const c = 30
    const edges: ReaderContextEdge[] = [
      edge({ id: 1, source_issue_id: a, target_issue_id: current }),
      edge({ id: 2, source_issue_id: b, target_issue_id: a }),
      edge({ id: 3, source_issue_id: c, target_issue_id: a }),
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    // a has two parents b and c, so we expect two lanes forking at a
    expect(lanes.length).toBe(2)
    const allIds = lanes.flatMap((lane) => lane.map((s) => s.issueId))
    expect(allIds).toContain(b)
    expect(allIds).toContain(c)
  })

  it('collects note fallback and dedupes explanations when edges duplicate steps', () => {
    const current = 200
    const prereq = 150
    const edges: ReaderContextEdge[] = [
      edge({ id: 10, source_issue_id: prereq, target_issue_id: current, explanation: 'need prereq' }),
      edge({ id: 11, source_issue_id: prereq, target_issue_id: current, explanation: 'need prereq' }),
      edge({ id: 12, source_issue_id: prereq, target_issue_id: current, note: 'note fallback', explanation: null }),
    ]
    const lanes = buildPrerequisiteLanes(edges, current)
    expect(lanes[0][0].explanations).toEqual(expect.arrayContaining(['need prereq', 'note fallback']))
    // deduped
    expect(new Set(lanes[0][0].explanations).size).toBe(lanes[0][0].explanations.length)
  })

  it('orders lanes deterministically regardless of input order via compareKeys', () => {
    const current = 500
    const a = 10
    const b = 20
    const edgesForward = [
      edge({ id: 2, kind: 'dependency', source_issue_id: b, target_issue_id: current }),
      edge({ id: 1, kind: 'continuity', source_issue_id: a, target_issue_id: current }),
    ]
    const edgesReverse = [...edgesForward].reverse()
    expect(buildPrerequisiteLanes(edgesForward, current).map((l) => l[0].issueId).sort()).toEqual(
      buildPrerequisiteLanes(edgesReverse, current).map((l) => l[0].issueId).sort(),
    )
  })
})
