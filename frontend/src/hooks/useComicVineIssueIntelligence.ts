import { useCallback } from 'react'
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
  options?: { enabled?: boolean },
): ComicVineIssueIntelligenceState {
  const enabled = !!issueId && (options?.enabled ?? true)
  const { data, isPending, refetch: queryRefetch } = useQuery({
    queryKey: issueId ? queryKeys.comicVine.issueIntelligence(issueId) : [],
    queryFn: () => comicVineApi.getIssueIntelligence(issueId!),
    enabled,
  })

  const refetch = useCallback(() => {
    void queryRefetch()
  }, [queryRefetch])

  return {
    metadata: data ?? null,
    isLoading: isPending,
    refetch,
  }
}
