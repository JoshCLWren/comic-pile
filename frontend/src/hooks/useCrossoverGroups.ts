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
const MAX_THREAD_IDS_PER_REQUEST = 200

function chunkThreadIds(threadIds: number[]): number[][] {
  const chunks: number[][] = []
  for (let index = 0; index < threadIds.length; index += MAX_THREAD_IDS_PER_REQUEST) {
    chunks.push(threadIds.slice(index, index + MAX_THREAD_IDS_PER_REQUEST))
  }
  return chunks
}

async function fetchCrossoverGroups(threadIds: number[]): Promise<Record<number, DependencyGroupSummary[]>> {
  const chunks = chunkThreadIds(threadIds)
  const responses = await Promise.all(
    chunks.map((threadIdChunk) => dependencyGroupsApi.listForThreads(threadIdChunk)),
  )
  const merged = Object.assign({}, ...responses) as Record<number, DependencyGroupSummary[]>
  // Ensure all requested thread IDs have an entry (empty array if not in response)
  const result: Record<number, DependencyGroupSummary[]> = {}
  for (const threadId of threadIds) {
    result[threadId] = merged[threadId] ?? []
  }
  return result
}

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  const requestedThreadIds = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b),
    [threadIds],
  )

  const { data, isPending, error } = useQuery({
    queryKey: requestedThreadIds.length > 0 ? queryKeys.crossover.groups(requestedThreadIds) : [],
    queryFn: async () => {
      try {
        return await fetchCrossoverGroups(requestedThreadIds)
      } catch (err) {
        throw err instanceof Error ? err : new Error('Failed to load crossovers')
      }
    },
    enabled: requestedThreadIds.length > 0,
  })

  if (requestedThreadIds.length === 0) {
    return { groupsByThreadId: EMPTY_GROUPS, isPending: false, error: null }
  }

  return {
    groupsByThreadId: data ?? EMPTY_GROUPS,
    isPending,
    error: (error as Error | null) ?? null,
  }
}
