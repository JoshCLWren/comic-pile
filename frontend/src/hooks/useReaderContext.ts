import { useQuery } from '@tanstack/react-query'
import {
  readerContextApi,
} from '../services/api-reader-context'
import { queryKeys } from '../query/queryKeys'

export function useReaderContext(
  issueId: number | null | undefined,
) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: issueId != null ? queryKeys.readerContext.forIssue(issueId) : [],
    queryFn: () => readerContextApi.get(issueId!),
    enabled: issueId != null,
  })

  return {
    context: data ?? null,
    isLoading: isPending,
    error: isError ? new Error('Unable to load reader context') : null,
    refetch,
  }
}
