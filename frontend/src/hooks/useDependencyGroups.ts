import { useQuery } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys'

interface DependencyGroupsState {
  groups: DependencyGroupSummary[]
  isLoading: boolean
  error: Error | null
}

const EMPTY_STATE: DependencyGroupsState = {
  groups: [],
  isLoading: false,
  error: null,
}

export interface DependencyGroupsApi {
  listForThread: (threadId: number) => Promise<DependencyGroupSummary[]>
}

export function useDependencyGroups(
  threadId: number | null | undefined,
  api: DependencyGroupsApi = dependencyGroupsApi,
): DependencyGroupsState {
  const { data, isPending, error } = useQuery({
    queryKey: threadId != null ? queryKeys.dependencies.forThread(threadId) : [],
    queryFn: async () => {
      try {
        return await api.listForThread(threadId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load reading-order groups')
      }
    },
    enabled: threadId != null,
    retry: false,
  })

  if (threadId == null) return EMPTY_STATE

  return {
    groups: data ?? [],
    isLoading: isPending,
    // SAFETY: the queryFn normalizes failures to Error, so the query error value is Error | null.
    error: (error as Error | null) ?? null,
  }
}
