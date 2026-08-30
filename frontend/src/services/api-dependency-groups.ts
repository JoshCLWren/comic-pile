import api from './api'
import type { Thread, Issue } from '../types'

export interface DependencyGroupMember {
  id: number
  thread_id: number | null
  issue_id: number | null
  /** Series title of the owning thread; null when the target no longer resolves. */
  series_title?: string | null
  /** Exact issue number for issue-level memberships; null for thread memberships. */
  issue_number?: string | null
}

export interface DependencyGroup {
  id: number
  name: string
  created_at: string
  memberships: DependencyGroupMember[]
}

export interface DependencyGroupSummary {
  id: number
  name: string
}

export interface DependencyGroupDetailMember {
  membership: DependencyGroupMember
  thread: Thread | null
  issue: Issue | null
  otherCrossovers: string[]
}

export interface DependencyGroupDetail {
  id: number
  name: string
  created_at: string
  memberships: DependencyGroupDetailMember[]
  readiness?: {
    node_type: string
    node_id: number
    is_readable: boolean
    evaluated_issue_id: number | null
    blockers: Array<{
      rule_id: number | null
      source_type: string
      source_id: number
      source_label: string
      satisfaction_type: string
      satisfied: boolean
      causing_issue_ids: number[]
      causing_member_issue_ids: number[]
      unread_issue_details: Array<{
        issue_id: number
        label: string
      }>
      note: string | null
      crossover_id?: number | null
      sequence_position?: number | null
    }>
  } | null
  linkedPlans: DependencyGroupSummary[]
}

export interface DependencyGroupIssueRangeResult {
  thread_id: number
  start_position: number
  end_position: number
  added_issue_ids: number[]
  already_present_issue_ids: number[]
}

export type DependencyGroupMemberTarget =
  | { thread_id: number; issue_id?: never }
  | { issue_id: number; thread_id?: never }

export const dependencyGroupsApi = {
  list: async (): Promise<DependencyGroup[]> => {
    return api.get<DependencyGroup[]>('/v1/reading-order-groups/')
  },

  create: async (name: string): Promise<DependencyGroup> => {
    return api.post<DependencyGroup>('/v1/reading-order-groups/', { name })
  },

  get: async (groupId: number): Promise<DependencyGroup> => {
    return api.get<DependencyGroup>(`/v1/reading-order-groups/${groupId}`)
  },

  getDetail: async (groupId: number): Promise<DependencyGroupDetail> => {
    return api.get<DependencyGroupDetail>(`/v1/reading-order-groups/${groupId}/detail`)
  },

  rename: async (groupId: number, name: string): Promise<DependencyGroup> => {
    return api.patch<DependencyGroup>(`/v1/reading-order-groups/${groupId}`, { name })
  },

  delete: async (groupId: number): Promise<void> => {
    await api.delete(`/v1/reading-order-groups/${groupId}`)
  },

  listForThread: async (threadId: number): Promise<DependencyGroupSummary[]> => {
    return api.get<DependencyGroupSummary[]>(
      `/v1/reading-order-groups/threads/${threadId}/groups`,
    )
  },

  plansForGroup: async (groupId: number): Promise<DependencyGroupSummary[]> => {
    return api.get<DependencyGroupSummary[]>(
      `/v1/reading-order-groups/${groupId}/plans`,
    )
  },

  listForThreads: async (
    threadIds: number[],
  ): Promise<Record<number, DependencyGroupSummary[]>> => {
    const entries = await Promise.all(
      threadIds.map(async (threadId) => [
        threadId,
        await api.get<DependencyGroupSummary[]>(
          `/v1/reading-order-groups/threads/${threadId}/groups`,
        ),
      ] as const),
    )
    return Object.fromEntries(entries)
  },

  addMember: async (
    groupId: number,
    target: DependencyGroupMemberTarget,
  ): Promise<DependencyGroupMember> => {
    return api.post<DependencyGroupMember>(
      `/v1/reading-order-groups/${groupId}/members`,
      target,
    )
  },

  addIssueRange: async (
    groupId: number,
    threadId: number,
    startPosition: number,
    endPosition: number,
  ): Promise<DependencyGroupIssueRangeResult> => {
    return api.post<DependencyGroupIssueRangeResult>(
      `/v1/reading-order-groups/${groupId}/issue-ranges`,
      {
        thread_id: threadId,
        start_position: startPosition,
        end_position: endPosition,
      },
    )
  },

  removeMember: async (groupId: number, memberId: number): Promise<void> => {
    await api.delete(
      `/v1/reading-order-groups/${groupId}/members/${memberId}`,
    )
  },
}
