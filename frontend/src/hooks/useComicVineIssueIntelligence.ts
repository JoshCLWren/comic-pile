import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api'
import { queryKeys } from '../query/queryKeys';

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
): ComicVineIssueIntelligenceState {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.comicVine.issueIntelligence(issueId),
    queryFn: async () => {
      if (!issueId) {
        return null;
      }
      return comicVineApi.getIssueIntelligence(issueId);
    },
    enabled: !!issueId,
  });

  return {
    metadata: data ?? null,
    isLoading: isPending,
    isError,
    error,
    refetch,
  };
}
