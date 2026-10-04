import { useQuery } from '@tanstack/react-query'
import { creatorComparisonApi } from '../services/creatorComparisonApi'
import { queryKeys } from '../query/queryKeys'
import type { CreatorComparisonResponse } from '../types/index'

function normalizeKeys(keys: string[]): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const key of keys) {
    const trimmed = key.trim()
    if (trimmed && !seen.has(trimmed)) {
      seen.add(trimmed)
      normalized.push(trimmed)
    }
  }
  return [...normalized].sort()
}

export function useCreatorComparison(keys: string[] | null | undefined) {
  const normalized = keys && keys.length > 0 ? normalizeKeys(keys) : []
  const enabled = normalized.length >= 2 && normalized.length <= 4

  const { data, isPending, isError, error } = useQuery<CreatorComparisonResponse>({
    queryKey: enabled ? queryKeys.creators.compare(normalized) : queryKeys.creators.compare([]),
    queryFn: () => creatorComparisonApi.getComparison(normalized),
    enabled,
  })

  return { data, isPending, isError, error }
}
