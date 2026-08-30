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

const EMPTY_STATE: ContinuityReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export interface UseContinuityReadinessOptions {
  /** Skip fetching because a parent already shares this exact readiness state. */
  skip?: boolean
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
  options: UseContinuityReadinessOptions = {},
): ContinuityReadinessState {
  const { skip = false } = options
  const { data, isPending, error, refetch } = useQuery({
    queryKey: issueId ? queryKeys.continuity.readiness('issue', issueId) : [],
    queryFn: async () => {
      try {
        return await continuityReadinessApi.evaluate('issue', issueId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load readiness')
      }
    },
    enabled: issueId != null && !skip,
  })

  if (issueId == null || skip) return EMPTY_STATE

  return {
    readiness: data ?? null,
    isLoading: isPending,
    error: (error as Error | null) ?? null,
    refetch: () => {
      void refetch()
    },
  }
}
