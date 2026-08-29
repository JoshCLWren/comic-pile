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
  /** Skip fetching because a parent already shares this exact readiness state. */
  skip?: boolean
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
  options: UseContinuityReadinessOptions = {},
): ContinuityReadinessState {
  const { skip = false } = options
  const enabled = issueId != null && !skip

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: enabled ? queryKeys.continuity.readiness(issueId!) : [],
    queryFn: () => continuityReadinessApi.evaluate('issue', issueId!),
    enabled,
  })

  return {
    readiness: data ?? null,
    isLoading: isPending,
    error: isError ? new Error('Unable to load readiness') : null,
    refetch,
  }
}
