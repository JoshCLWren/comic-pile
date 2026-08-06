import api from './api'

export interface DependencyGroupMember {
  id: number
  thread_id: number | null
  issue_id: number | null
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
