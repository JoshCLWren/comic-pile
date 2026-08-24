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
  const uniqueSortedIds = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b),
    [threadIds],
  )

  const query = useQuery({
    queryKey: queryKeys.dependencyGroups.forThreads(uniqueSortedIds),
    queryFn: async () => {
      if (!enabled) {
        return EMPTY_GROUPS
      }
      return dependencyGroupsApi.listForThreads(uniqueSortedIds)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  const result = query.data ?? EMPTY_GROUPS
  const groupsByThreadId: Record<number, DependencyGroupSummary[]> = {}
  for (const id of uniqueSortedIds) {
    groupsByThreadId[id] = result[id] ?? []
  }

  return {
    groupsByThreadId,
    isPending: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
  }
}
