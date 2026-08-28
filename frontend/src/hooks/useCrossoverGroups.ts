import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys';

interface CrossoverGroupsState {
  groupsByThreadId: Record<number, DependencyGroupSummary[]>
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

// Helper function to chunk thread IDs for batching
function chunkThreadIds(threadIds: number[]): number[][] {
  const chunks: number[][] = []
  const MAX_THREAD_IDS_PER_REQUEST = 200
  for (let index = 0; index < threadIds.length; index += MAX_THREAD_IDS_PER_REQUEST) {
    chunks.push(threadIds.slice(index, index + MAX_THREAD_IDS_PER_REQUEST))
  }
  return chunks
}

// Helper function to fetch crossover groups with batching
async function fetchCrossoverGroups(threadIds: number[]): Promise<Record<number, DependencyGroupSummary[]>> {
  if (threadIds.length === 0) {
    return {};
  }

  const requests = [...new Set(threadIds)].sort((a, b) => a - b); // Deduplicate and sort
  
  try {
    const responses = await Promise.all(
      chunkThreadIds(requests).map((threadIdChunk) =>
        dependencyGroupsApi.listForThreads(threadIdChunk),
      ),
    )
    return Object.assign({}, ...responses) as Record<number, DependencyGroupSummary[]>
  } catch (error) {
    throw error instanceof Error ? error : new Error('Failed to load crossovers')
  }
}

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  // Create a stable key from sorted, deduplicated thread IDs
  const threadIdsKey = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b),
    [threadIds]
  );

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.dependencyGroups.forThreads(threadIdsKey),
    queryFn: () => fetchCrossoverGroups(threadIdsKey),
  });

  return {
    groupsByThreadId: data ?? {},
    isLoading: isPending,
    isError,
    error,
    refetch,
  };
}
