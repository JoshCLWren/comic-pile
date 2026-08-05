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

export type DependencyGroupMemberTarget =
  | { thread_id: number; issue_id?: never }
  | { issue_id: number; thread_id?: never }

export const dependencyGroupsApi = {
  list: async (): Promise<DependencyGroup[]> => {
    return api.get<DependencyGroup[]>('/v1/dependencies/reading-order-groups/')
  },

  create: async (name: string): Promise<DependencyGroup> => {
    return api.post<DependencyGroup>('/v1/dependencies/reading-order-groups/', { name })
  },

  get: async (groupId: number): Promise<DependencyGroup> => {
    return api.get<DependencyGroup>(`/v1/dependencies/reading-order-groups/${groupId}`)
  },

  rename: async (groupId: number, name: string): Promise<DependencyGroup> => {
    return api.patch<DependencyGroup>(`/v1/dependencies/reading-order-groups/${groupId}`, { name })
  },

  delete: async (groupId: number): Promise<void> => {
    await api.delete(`/v1/dependencies/reading-order-groups/${groupId}`)
  },

  listForThread: async (threadId: number): Promise<DependencyGroupSummary[]> => {
    return api.get<DependencyGroupSummary[]>(
      `/v1/dependencies/reading-order-groups/threads/${threadId}/groups`,
    )
  },

  addMember: async (
    groupId: number,
    target: DependencyGroupMemberTarget,
  ): Promise<DependencyGroupMember> => {
    return api.post<DependencyGroupMember>(
      `/v1/dependencies/reading-order-groups/${groupId}/members`,
      target,
    )
  },

  removeMember: async (groupId: number, memberId: number): Promise<void> => {
    await api.delete(
      `/v1/dependencies/reading-order-groups/${groupId}/members/${memberId}`,
    )
  },
}
