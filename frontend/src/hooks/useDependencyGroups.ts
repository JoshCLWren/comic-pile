import { useQuery } from '@tanstack/react-query';
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { queryKeys } from '../query/queryKeys';

interface DependencyGroupsState {
  groups: DependencyGroupSummary[]
  isLoading: boolean
  isError: boolean
  error: Error | null
}

export function useDependencyGroups(threadId: number | null | undefined): DependencyGroupsState {
  const { data, isPending, isError, error } = useQuery({
    queryKey: queryKeys.dependencyGroups.forThread(threadId!),
    queryFn: async () => {
      if (threadId == null) {
        return [];
      }
      return dependencyGroupsApi.listForThread(threadId);
    },
    enabled: threadId != null,
  });

  return {
    groups: data ?? [],
    isLoading: isPending,
    isError,
    error,
  };
}
