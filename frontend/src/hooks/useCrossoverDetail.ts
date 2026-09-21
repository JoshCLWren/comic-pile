import { useQuery } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroup,
  type DependencyGroupSummary,
  type DependencyGroupMember,
} from '../services/api-dependency-groups'
import { Thread, Issue } from '../types'
import { queryKeys } from '../query/queryKeys'
import { getApiErrorDetail } from '../utils/apiError'

export interface CrossoverDetailState {
  crossover: DependencyGroup | null
  members: CrossoverMember[]
  linkedPlans: DependencyGroupSummary[]
  isLoading: boolean
  error: string | null
}

export type CrossoverMember = {
  membership: DependencyGroupMember
  thread: Thread | null
  issue: Issue | null
  other_crossovers: string[]
}

export function useCrossoverDetail(
  groupId: number | null | undefined,
): CrossoverDetailState & { refetch: () => Promise<void> } {
  const validId = groupId != null && Number.isFinite(groupId) && groupId > 0 ? groupId : null
  const {
    data,
    isPending,
    error: err,
    refetch: queryRefetch,
  } = useQuery({
    queryKey: validId ? queryKeys.crossover.detail(validId) : [],
    queryFn: async () => {
      if (!validId) throw new Error('No group ID')
      return dependencyGroupsApi.getDetail(validId)
    },
    enabled: !!validId,
    retry: false,
  })
  const error = err ? getApiErrorDetail(err as Error) : null
  const crossover = data
    ? {
        id: data.id,
        name: data.name,
        created_at: data.created_at,
        memberships: data.memberships.map((m) => m.membership),
      }
    : null
  const members = data
    ? data.memberships.map((m) => ({
        membership: m.membership,
        thread: m.thread,
        issue: m.issue,
        other_crossovers: m.other_crossovers,
      }))
    : []
  const linkedPlans = data?.linked_plans ?? []
  const refetch = async (): Promise<void> => {
    await queryRefetch()
  }
  return { crossover, members, linkedPlans, isLoading: isPending && !!validId, error, refetch }
}
