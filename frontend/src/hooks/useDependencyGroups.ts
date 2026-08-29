import { useQuery } from '@tanstack/react-query'
import {
  dependencyGroupsApi,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys'

export function useDependencyGroups(threadId: number | null | undefined) {
  const { data, isPending, isError } = useQuery({
    queryKey: threadId != null ? queryKeys.dependencyGroups.forThread(threadId) : [],
    queryFn: () => dependencyGroupsApi.listForThread(threadId!),
    enabled: threadId != null,
  })

  return {
    groups: data ?? [],
    isLoading: isPending,
    error: isError ? new Error('Unable to load reading-order groups') : null,
  }
}
