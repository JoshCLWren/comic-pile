import { useQuery } from '@tanstack/react-query'
import { comicVineApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
) {
  const { data, isPending, refetch } = useQuery({
    queryKey: issueId ? queryKeys.comicVine.issueIntelligence(issueId) : [],
    queryFn: () => comicVineApi.getIssueIntelligence(issueId!),
    enabled: !!issueId,
  })

  return { metadata: data ?? null, isLoading: isPending, refetch }
}
