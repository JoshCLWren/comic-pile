import { useQuery } from '@tanstack/react-query'
import { creatorsApi, type CreatorSummariesResponse } from '../services/creatorsApi'
import { queryKeys } from '../query/queryKeys'

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

export function canonicalCreatorKey(creatorId: number): string {
  return `creator:${creatorId}`
}

export function useCreatorSummaries(keys: string[] | null | undefined) {
  const normalized = keys && keys.length > 0 ? normalizeKeys(keys) : []
  const enabled = normalized.length > 0

  const { data, isPending, isError, error } = useQuery({
    queryKey: enabled ? queryKeys.creators.summaries(normalized) : queryKeys.creators.summaries([]),
    queryFn: () => creatorsApi.getSummaries(normalized),
    enabled,
  })

  return { data, isPending, isError, error }
}
