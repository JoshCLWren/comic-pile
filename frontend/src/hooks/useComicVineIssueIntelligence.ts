import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import { queryKeys } from '../query/queryKeys'

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => Promise<ComicVineIssueIntelligence | null>
}

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
  options?: { enabled?: boolean },
): ComicVineIssueIntelligenceState {
  const enabled = !!issueId && (options?.enabled ?? true)
  const { data, isPending, isError, error, refetch: queryRefetch } = useQuery({
    queryKey: issueId ? queryKeys.comicVine.issueIntelligence(issueId) : [],
    queryFn: () => comicVineApi.getIssueIntelligence(issueId!),
    enabled,
  })

  // Expose an awaitable refetch and its latest value so the exact-issue
  // hydration contract can render persisted credits only after the scoped
  // re-read settles. There is no polling timer to re-arm (#5841).
  const refetch = useCallback(async () => {
    const result = await queryRefetch()
    return result.data ?? null
  }, [queryRefetch])

  return {
    metadata: data ?? null,
    isLoading: isPending,
    isError,
    error,
    refetch,
  }
}
