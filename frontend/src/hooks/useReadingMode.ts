import { useQuery } from '@tanstack/react-query'
import { getReadingMode } from '../services/readingMode'
import { queryKeys } from '../query/queryKeys'

/** Canonical scoped reading-mode state shared by the launcher and Roll header. */
export function useReadingMode() {
  return useQuery({
    queryKey: queryKeys.readingMode.state(),
    queryFn: getReadingMode,
    staleTime: 60_000,
    retry: false,
  })
}
