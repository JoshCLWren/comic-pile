import { useQuery } from '@tanstack/react-query';
import {
  readerContextApi,
  type ReaderContextResponse,
} from '../services/api-reader-context'
import { queryKeys } from '../query/queryKeys';

interface ReaderContextState {
  context: ReaderContextResponse | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

export function useReaderContext(
  issueId: number | null | undefined,
): ReaderContextState {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.readerContext.issue(issueId!),
    queryFn: async () => {
      if (issueId == null) {
        return null;
      }
      return readerContextApi.get(issueId);
    },
    enabled: issueId != null,
  });

  return {
    context: data ?? null,
    isLoading: isPending,
    isError,
    error,
    refetch,
  };
}
