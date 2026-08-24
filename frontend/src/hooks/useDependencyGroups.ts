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

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Unable to load reading-order groups')
}

export function useDependencyGroups(threadId: number | null | undefined): DependencyGroupsState {
  const enabled = threadId != null

  const query = useQuery({
    queryKey: queryKeys.dependencyGroups.forThread(threadId ?? -1),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No thread ID')
      }
      return dependencyGroupsApi.listForThread(threadId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    groups: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
  }
}
