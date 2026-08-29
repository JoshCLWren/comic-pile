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

interface PendingCrossoverRequest {
  threadIds: number[]
  resolve: (groupsByThreadId: Record<number, DependencyGroupSummary[]>) => void
  reject: (error: unknown) => void
}

const EMPTY_GROUPS: Record<number, DependencyGroupSummary[]> = {}
const MAX_THREAD_IDS_PER_REQUEST = 200
let pendingRequests: PendingCrossoverRequest[] = []
let flushScheduled = false

function chunkThreadIds(threadIds: number[]): number[][] {
  const chunks: number[][] = []
  for (let index = 0; index < threadIds.length; index += MAX_THREAD_IDS_PER_REQUEST) {
    chunks.push(threadIds.slice(index, index + MAX_THREAD_IDS_PER_REQUEST))
  }
  return chunks
}

async function flushPendingRequests() {
  const requests = pendingRequests
  pendingRequests = []
  flushScheduled = false

  const allThreadIds = [...new Set(requests.flatMap((request) => request.threadIds))]

  try {
    const responses = await Promise.all(
      chunkThreadIds(allThreadIds).map((threadIdChunk) =>
        dependencyGroupsApi.listForThreads(threadIdChunk),
      ),
    )
    const mergedGroupsByThreadId = Object.assign({}, ...responses) as Record<number, DependencyGroupSummary[]>

    requests.forEach(({ threadIds, resolve }) => {
      const requestedGroups = Object.fromEntries(
        threadIds.map((threadId) => [threadId, mergedGroupsByThreadId[threadId] ?? []]),
      )
      resolve(requestedGroups)
    })
  } catch (error) {
    requests.forEach(({ reject }) => reject(error))
  }
}

function requestCrossoverGroups(threadIds: number[]): Promise<Record<number, DependencyGroupSummary[]>> {
  return new Promise((resolve, reject) => {
    pendingRequests.push({ threadIds, resolve, reject })
    if (!flushScheduled) {
      flushScheduled = true
      queueMicrotask(() => {
        void flushPendingRequests()
      })
    }
  })
}

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  const requestKey = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b).join(','),
    [threadIds],
  )
  const requestedThreadIds = requestKey ? requestKey.split(',').map((threadId) => Number(threadId)) : []

  const { data, isPending, error } = useQuery({
    queryKey: requestedThreadIds.length > 0 ? queryKeys.crossover.groups(requestedThreadIds) : [],
    queryFn: async () => {
      try {
        return await requestCrossoverGroups(requestedThreadIds)
      } catch (err) {
        throw err instanceof Error ? err : new Error('Failed to load crossovers')
      }
    },
    enabled: requestedThreadIds.length > 0,
    initialData: EMPTY_GROUPS,
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
