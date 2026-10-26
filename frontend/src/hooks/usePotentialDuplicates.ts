import { useQuery } from '@tanstack/react-query'
import { useDebounce } from './useDebounce'
import { queryKeys } from '../query/queryKeys'
import { threadsApi } from '../services/api-threads'
import type { CheckPotentialDuplicatesRequest } from '../types'

/** User-scoped advisory matches; disabled and cleared immediately for an empty title. */
export function usePotentialDuplicates(input: CheckPotentialDuplicatesRequest, enabled: boolean) {
  const title = useDebounce(input.title.trim(), 300)
  const params = { ...input, title, format: input.format.trim() }
  const active = enabled && !!input.title.trim() && !!params.format && title === input.title.trim()
  const query = useQuery({
    queryKey: queryKeys.thread.potentialDuplicates(params),
    queryFn: () => threadsApi.checkPotentialDuplicates(params),
    enabled: active,
    retry: false,
  })
  return { matches: active ? query.data?.matches ?? [] : [], isChecking: active && query.isFetching }
}
