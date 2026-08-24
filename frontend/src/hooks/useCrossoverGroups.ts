import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys'

interface CrossoverGroupsState {
  groupsByThreadId: Record<number, DependencyGroupSummary[]>
  isPending: boolean
  error: Error | null
}

const EMPTY_GROUPS: Record<number, DependencyGroupSummary[]> = {}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Failed to load crossovers')
}

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  const requestKey = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b).join(','),
    [threadIds],
  )

  const enabled = requestKey.length > 0

  const query = useQuery({
    queryKey: queryKeys.dependencyGroups.forThreads(
      requestKey ? requestKey.split(',').map(Number) : [],
    ),
    queryFn: async () => {
      if (!enabled) {
        return EMPTY_GROUPS
      }
      const requestedThreadIds = requestKey.split(',').map(Number)
      return dependencyGroupsApi.listForThreads(requestedThreadIds)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    groupsByThreadId: query.data ?? EMPTY_GROUPS,
    isPending: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
  }
}
