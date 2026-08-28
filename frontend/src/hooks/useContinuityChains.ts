import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  continuityReadinessApi,
  type ContinuityChainResponse,
} from '../services/api-continuity-readiness'
import { queryKeys } from '../query/queryKeys';

interface ContinuityChainsState {
  chains: ContinuityChainResponse | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

export function useContinuityChains(
  issueId: number | null | undefined,
): ContinuityChainsState {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.continuity.chains('issue', issueId),
    queryFn: async () => {
      if (issueId == null) {
        return null;
      }
      return continuityReadinessApi.resolveChains('issue', issueId);
    },
    enabled: issueId != null,
  });

  return {
    chains: data ?? null,
    isLoading: isPending,
    isError,
    error,
    refetch,
  };
}
