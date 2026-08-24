import { useQuery } from '@tanstack/react-query'
import {
  continuityReadinessApi,
  type ContinuityReadinessResponse,
} from '../services/api-continuity-readiness'
import { queryKeys } from '../query/queryKeys'

interface ContinuityReadinessState {
  readiness: ContinuityReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Unable to load readiness')
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
): ContinuityReadinessState {
  const enabled = issueId != null

  const query = useQuery({
    queryKey: queryKeys.continuity.readiness('issue', issueId ?? -1),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No issue ID')
      }
      return continuityReadinessApi.evaluate('issue', issueId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    readiness: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
    refetch: query.refetch,
  }
}