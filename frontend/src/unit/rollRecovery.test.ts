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
})
