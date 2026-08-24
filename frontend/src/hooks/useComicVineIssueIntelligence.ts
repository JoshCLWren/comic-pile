import { useQuery } from '@tanstack/react-query'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api'
import { queryKeys } from '../query/queryKeys'

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Unable to load comic intelligence')
}

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
): ComicVineIssueIntelligenceState {
  const enabled = issueId != null

  const query = useQuery({
    queryKey: queryKeys.comicVine.issueIntelligence(issueId ?? -1),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No issue ID')
      }
      return comicVineApi.getIssueIntelligence(issueId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    metadata: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
    refetch: query.refetch,
  }
}
