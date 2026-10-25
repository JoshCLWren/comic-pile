import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import { queryKeys } from '../query/queryKeys'

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  refetch: () => Promise<void>
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

  // Expose an awaitable refetch: callers that re-arm a bounded timer need to
  // know when the in-flight request settled, otherwise a slow provider response
  // overlaps with the next scheduled refetch and React Query cancels it.
  const refetch = useCallback(async () => {
    await queryRefetch()
  }, [queryRefetch])

  return {
    metadata: data ?? null,
    isLoading: isPending,
    refetch,
  }
}
