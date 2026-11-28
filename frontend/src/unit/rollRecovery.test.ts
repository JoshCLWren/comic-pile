import { describe, expect, it } from 'vitest'
import type {
  GetIssueDependenciesResponse,
  IssueCardsResponse,
  ReadingGraphResponse,
} from '../generated/nativeV2Client'
import { buildRollRecovery } from '../services/rollRecovery'
import type { RollPendingSelection } from '../services/rollPendingSelection'
import type { components } from '../generated/openapi'

type ReadingGraphCycle = components['schemas']['ReadingGraphCycle']

type IssueCard = IssueCardsResponse['items'][number]

const PENDING: RollPendingSelection = {
  issue_id: 10,
  thread_id: 3,
  issue_number: '10',
  selected_at: 1_700_000_000_000,
}

function card(issueId: number, status: string): IssueCard {
  return {
    issue_id: issueId,
    thread_id: 7,
    thread_title: 'Earlier Series',
    issue_number: '3',
    display_issue_number: '3',
    has_confirmed_identity: false,
    mapping_state: 'unmapped',
    status,
  }
}

function dependencies(): GetIssueDependenciesResponse {
  return {
    issue_id: 10,
    incoming: [{
      dependency_id: 55,
      source_issue_id: 9,
      source_issue_number: '3',
      source_thread_id: 7,
      source_thread_title: 'Earlier Series',
    }],
    outgoing: [],
  }
}

function graphWithCycle(): ReadingGraphResponse {
  const cycle: ReadingGraphCycle = {
    message: 'cycle',
    edges: [{
      kind: 'prerequisite',
      origin: 'reading_list',
      source: { issue_id: 10, issue_number: '10', series_title: 'Current', thread_id: 3 },
      target: { issue_id: 9, issue_number: '3', series_title: 'Earlier Series', thread_id: 7 },
    }],
  }
  return {
    affected_lists: [],
    affected_threads: [],
    cycles: [cycle],
    cyclic_issue_ids: [9, 10],
    repairs: [],
    status: 'cycle',
    unresolved_reference_count: 0,
  }
}

describe('scoped Roll recovery view model', () => {
  it('reports an unmet owner-scoped dependency and marks readable prerequisites', () => {
    const recovery = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [9, 10],
      dependencies: dependencies(),
      prerequisiteCards: [card(9, 'unread')],
      graph: null,
      originalTitle: 'Current Series',
    })

    expect(recovery).not.toBeNull()
    expect(recovery?.original_thread_id).toBe(3)
    expect(recovery?.original_thread_title).toBe('Current Series')
    expect(recovery?.direct_blockers[0]).toMatchObject({
      source_id: 9,
      source_label: 'Earlier Series #3',
      satisfied: false,
    })
    expect(recovery?.readable_prerequisites).toEqual([{
      node_type: 'issue',
      node_id: 9,
      label: 'Earlier Series #3',
      is_readable: true,
    }])
    expect(recovery?.chains).toHaveLength(1)
  })

  it('does not block on a read prerequisite', () => {
    expect(buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: dependencies(),
      prerequisiteCards: [card(9, 'read')],
      graph: null,
    })).toBeNull()
  })

  it('surfaces canonical reading-graph diagnostics for the selected issue', () => {
    const recovery = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: null,
      prerequisiteCards: [],
      graph: graphWithCycle(),
    })
    expect(recovery?.diagnostics).toEqual([{
      code: 'cycle_detected',
      node_type: 'issue',
      node_id: 10,
    }])
  })

  it('returns null while the scoped dependency read has not arrived', () => {
    expect(buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: null,
      prerequisiteCards: [],
      graph: null,
    })).toBeNull()
  })

  it('caps readable prerequisites at 20 and de-duplicates repeated source ids', () => {
    const edges = Array.from({ length: 24 }, (_, index) => ({
      dependency_id: 100 + index,
      source_issue_id: 200 + index,
      source_issue_number: String(index),
      source_thread_id: 7,
      source_thread_title: 'Earlier Series',
    }))
    // A second edge naming an already-seen source must not create another chain.
    edges.push({ ...edges[0], dependency_id: 999 })

    const recovery = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: edges.map((edge) => edge.source_issue_id),
      dependencies: { issue_id: 10, incoming: edges, outgoing: [] },
      prerequisiteCards: edges.map((edge) => card(edge.source_issue_id, 'unread')),
      graph: null,
    })

    expect(recovery?.direct_blockers).toHaveLength(edges.length)
    expect(recovery?.readable_prerequisites).toHaveLength(20)
    expect(recovery?.chains).toHaveLength(20)
  })

  it('marks an unread prerequisite outside the eligible pool as not readable', () => {
    const recovery = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: dependencies(),
      prerequisiteCards: [card(9, 'unread')],
      graph: null,
    })
    expect(recovery?.readable_prerequisites[0]?.is_readable).toBe(false)
    expect(recovery?.chains[0]?.[0]?.is_readable).toBe(false)
  })

  it('treats a prerequisite with no loaded card as an unmet blocker', () => {
    const recovery = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [9, 10],
      dependencies: dependencies(),
      prerequisiteCards: [],
      graph: null,
    })
    expect(recovery?.direct_blockers[0]?.source_id).toBe(9)
    expect(recovery?.readable_prerequisites).toHaveLength(1)
  })

  it('ignores dependency edges that belong to a different pending issue', () => {
    expect(buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [9, 10],
      dependencies: { ...dependencies(), issue_id: 11 },
      prerequisiteCards: [card(9, 'unread')],
      graph: null,
    })).toBeNull()
  })

  it('ignores canonical cycles that do not touch the pending issue', () => {
    const cycle: ReadingGraphCycle = {
      message: 'cycle',
      edges: [{
        kind: 'prerequisite',
        origin: 'reading_list',
        source: { issue_id: 7, issue_number: '7', series_title: 'Other', thread_id: 2 },
        target: { issue_id: 8, issue_number: '8', series_title: 'Other', thread_id: 2 },
      }],
    }
    const graph: ReadingGraphResponse = {
      affected_lists: [],
      affected_threads: [],
      cycles: [cycle],
      cyclic_issue_ids: [7, 8],
      repairs: [],
      status: 'cycle',
      unresolved_reference_count: 0,
    }
    expect(buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: null,
      prerequisiteCards: [],
      graph,
    })).toBeNull()
  })

  it('falls back to the pending issue number or id when no card title is present', () => {
    const withNumber = buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: dependencies(),
      prerequisiteCards: [card(9, 'unread')],
      graph: null,
    })
    expect(withNumber?.original_thread_title).toBe('Issue 10')

    const withoutNumber = buildRollRecovery({
      pending: { ...PENDING, issue_number: null },
      eligibleIssueIds: [10],
      dependencies: dependencies(),
      prerequisiteCards: [card(9, 'unread')],
      graph: null,
    })
    expect(withoutNumber?.original_thread_title).toBe('Issue 10')
  })

  it('returns null for a cached graph that reports no cycles', () => {
    const graph = graphWithCycle()
    expect(buildRollRecovery({
      pending: PENDING,
      eligibleIssueIds: [10],
      dependencies: null,
      prerequisiteCards: [],
      graph: { ...graph, cycles: [] },
    })).toBeNull()
  })
})
