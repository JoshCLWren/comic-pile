import { useQuery } from '@tanstack/react-query'
import {
  continuityReadinessApi,
  type ContinuityChainResponse,
} from '../services/api-continuity-readiness'
import { queryKeys } from '../query/queryKeys'

interface ContinuityChainsState {
  chains: ContinuityChainResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ContinuityChainsState = {
  chains: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useContinuityChains(
  issueId: number | null | undefined,
): ContinuityChainsState {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: issueId ? queryKeys.continuity.chains('issue', issueId) : [],
    queryFn: async () => {
      try {
        return await continuityReadinessApi.resolveChains('issue', issueId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load chain')
      }
    },
    enabled: issueId != null,
  })

  if (issueId == null) return EMPTY_STATE

  return {
    chains: data ?? null,
    isLoading: isPending,
    error: (error as Error | null) ?? null,
    refetch: () => {
      void refetch()
    },
  }
}
