import { useQuery } from '@tanstack/react-query'
import {
  continuityReadinessApi,
} from '../services/api-continuity-readiness'
import { queryKeys } from '../query/queryKeys'

export function useContinuityChains(
  issueId: number | null | undefined,
) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: issueId != null ? queryKeys.continuity.chains(issueId) : [],
    queryFn: () => continuityReadinessApi.resolveChains('issue', issueId!),
    enabled: issueId != null,
  })

  return {
    chains: data ?? null,
    isLoading: isPending,
    error: isError ? new Error('Unable to load chain') : null,
    refetch,
  }
}
