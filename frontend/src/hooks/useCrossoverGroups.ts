import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys'

const EMPTY_GROUPS: Record<number, DependencyGroupSummary[]> = {}
const MAX_THREAD_IDS_PER_REQUEST = 200

function chunkThreadIds(threadIds: number[]): number[][] {
  const chunks: number[][] = []
  for (let index = 0; index < threadIds.length; index += MAX_THREAD_IDS_PER_REQUEST) {
    chunks.push(threadIds.slice(index, index + MAX_THREAD_IDS_PER_REQUEST))
  }
  return chunks
}

export function useCrossoverGroups(threadIds: number[]) {
  const sortedIds = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b),
    [threadIds],
  )
  const queryKey = sortedIds.length > 0
    ? queryKeys.dependencyGroups.forThreads(sortedIds)
    : []

  const { data, isPending, isError } = useQuery({
    queryKey,
    queryFn: async () => {
      const responses = await Promise.all(
        chunkThreadIds(sortedIds).map((chunk) =>
          dependencyGroupsApi.listForThreads(chunk),
        ),
      )
      return Object.assign({}, ...responses) as Record<number, DependencyGroupSummary[]>
    },
    enabled: sortedIds.length > 0,
  })

  return {
    groupsByThreadId: data ?? EMPTY_GROUPS,
    isPending: sortedIds.length > 0 && isPending,
    error: isError ? new Error('Failed to load crossovers') : null,
  }
}
