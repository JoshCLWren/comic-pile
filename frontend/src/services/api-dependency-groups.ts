import { defaultHttpClient, type HttpClient } from './httpClient'
import type { Thread, Issue } from '../types'

export interface DependencyGroupMember {
  id: number
  thread_id: number | null
  issue_id: number | null
  /** Series title of the owning thread; null when the target no longer resolves. */
  series_title?: string | null
  /** Exact issue number for issue-level memberships; null for thread memberships. */
  issue_number?: string | null
  /** Authoritative position of an issue-level membership within the crossover's reading order. Thread memberships ignore this field. */
  sequence_order?: number | null
}

export interface DependencyGroup {
  id: number
  name: string
  created_at: string
  memberships: DependencyGroupMember[]
  /** Countable member issues the reader has completed; 0 when nothing is countable. */
  read_issues?: number
  /** Total countable member issues across migrated series and direct issues; 0 if none. */
  total_issues?: number
  /** Computed reading progress as a percentage string, e.g. "40%". */
  reading_progress?: string
}

export interface DependencyGroupSummary {
  id: number
  name: string
}

export interface DependencyGroupDetailMember {
  membership: DependencyGroupMember
  thread: Thread | null
  issue: Issue | null
  other_crossovers: string[]
}

export interface DependencyGroupDetail {
  id: number
  name: string
  created_at: string
  memberships: DependencyGroupDetailMember[]
  linked_plans: DependencyGroupSummary[]
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

/**
 * Build the dependency-group service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every dependency-group request.
 * @returns The dependency groups API bound to `client`.
 */
export function createDependencyGroupsApi(client: HttpClient) {
  return {
    list: async (): Promise<DependencyGroup[]> => {
      return client.get<DependencyGroup[]>('/v2/readingOrderGroups')
    },

    create: async (name: string): Promise<DependencyGroup> => {
      return client.post<DependencyGroup>('/v2/readingOrderGroups', { name })
    },

    /**
     * Canonical v2 Get. The server folds the enriched detail view into this
     * single resource read, so there is no separate `/detail` call.
     */
    get: async (groupId: number): Promise<DependencyGroupDetail> => {
      return client.get<DependencyGroupDetail>(`/v2/readingOrderGroups/${groupId}`)
    },

    rename: async (groupId: number, name: string): Promise<DependencyGroup> => {
      return client.patch<DependencyGroup>(`/v2/readingOrderGroups/${groupId}`, { name })
    },

    delete: async (groupId: number): Promise<void> => {
      await client.delete(`/v2/readingOrderGroups/${groupId}`)
    },

    listForThread: async (threadId: number): Promise<DependencyGroupSummary[]> => {
      return client.get<DependencyGroupSummary[]>(
        `/v2/threads/${threadId}/reading-order-group-memberships`,
      )
    },

    plansForGroup: async (groupId: number): Promise<DependencyGroupSummary[]> => {
      return client.get<DependencyGroupSummary[]>(
        `/v2/reading-order-groups/${groupId}/reading-plans`,
      )
    },

    /**
     * Load crossover memberships for several threads in one bounded request.
     *
     * Uses the backend batch action `POST /v2/reading-order-groups:resolveMemberships`
     * (AIP-136), which resolves ownership once and returns all requested thread
     * memberships in a single response.
     */
    listForThreads: async (
      threadIds: number[],
    ): Promise<Record<number, DependencyGroupSummary[]>> => {
      return client.post<Record<number, DependencyGroupSummary[]>>(
        '/v2/reading-order-groups:resolveMemberships',
        { thread_ids: threadIds },
      )
    },

    addMember: async (
      groupId: number,
      target: DependencyGroupMemberTarget,
    ): Promise<DependencyGroupMember> => {
      return client.post<DependencyGroupMember>(
        `/v2/reading-order-groups/${groupId}/members`,
        target,
      )
    },

    addIssueRange: async (
      groupId: number,
      threadId: number,
      startPosition: number,
      endPosition: number,
    ): Promise<DependencyGroupIssueRangeResult> => {
      return client.post<DependencyGroupIssueRangeResult>(
        `/v2/reading-order-groups/${groupId}/issue-ranges`,
        {
          thread_id: threadId,
          start_position: startPosition,
          end_position: endPosition,
        },
      )
    },

    removeMember: async (groupId: number, memberId: number): Promise<void> => {
      await client.delete(
        `/v2/reading-order-groups/${groupId}/members/${memberId}`,
      )
    },
    }
}

export const dependencyGroupsApi = createDependencyGroupsApi(defaultHttpClient())
