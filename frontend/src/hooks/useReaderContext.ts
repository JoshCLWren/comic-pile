import { useQuery } from '@tanstack/react-query'
import {
  readerContextApi,
  type ReaderContextResponse,
} from '../services/api-reader-context'
import { queryKeys } from '../query/queryKeys'

interface ReaderContextState {
  context: ReaderContextResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ReaderContextState = {
  context: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useReaderContext(issueId: number | null | undefined): ReaderContextState {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: issueId ? queryKeys.readerContext.detail(issueId) : [],
    queryFn: async () => {
      try {
        return await readerContextApi.get(issueId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load reader context')
      }
    },
    enabled: issueId != null,
  })

  if (issueId == null) return EMPTY_STATE

  return {
    context: data ?? null,
    isLoading: isPending,
    error: (error as Error | null) ?? null,
    refetch: () => {
      void refetch()
    },
  }
}
