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

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Unable to load chain')
}

export function useContinuityChains(
  issueId: number | null | undefined,
): ContinuityChainsState {
  const enabled = issueId != null

  const query = useQuery({
    queryKey: enabled ? queryKeys.continuity.chains('issue', issueId) : undefined,
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No issue ID')
      }
      return continuityReadinessApi.resolveChains('issue', issueId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    chains: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
    refetch: query.refetch,
  }
}