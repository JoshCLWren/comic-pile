import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  continuityReadinessApi,
  type ContinuityReadinessResponse,
} from '../services/api-continuity-readiness'
import { queryKeys } from '../query/queryKeys'

export interface ContinuityReadinessState {
  readiness: ContinuityReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

export interface UseContinuityReadinessOptions {
  skip?: boolean
}

function normalizeContinuityReadinessError(error: unknown): Error | null {
  if (error == null) return null
  if (error instanceof Error) return error
  return new Error('Unable to load readiness')
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
  options: UseContinuityReadinessOptions = {},
): ContinuityReadinessState {
  const { skip = false } = options
  const enabled = issueId != null && !skip

  const query = useQuery({
    queryKey: enabled ? queryKeys.continuity.readiness('issue', issueId) : undefined,
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

  const refetch = useCallback(() => query.refetch(), [query])

  return {
    readiness: query.data ?? null,
    isLoading: query.isLoading,
    error: normalizeContinuityReadinessError(query.error),
    refetch,
  }
}