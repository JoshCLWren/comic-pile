import { useQuery } from '@tanstack/react-query'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import { queryKeys } from '../query/queryKeys'

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  refetch: () => void
}

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
): ComicVineIssueIntelligenceState {
  const { data, isPending, refetch } = useQuery({
    queryKey: issueId ? queryKeys.comicVine.issueIntelligence(issueId) : [],
    queryFn: () => comicVineApi.getIssueIntelligence(issueId!),
    enabled: !!issueId,
  })

  return {
    metadata: data ?? null,
    isLoading: isPending,
    refetch: () => {
      void refetch()
    },
  }
}
