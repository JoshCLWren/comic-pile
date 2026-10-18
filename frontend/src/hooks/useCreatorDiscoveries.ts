import { useQuery } from '@tanstack/react-query'
import { creatorDiscoveryApi } from '../services/creatorDiscoveryApi'
import { queryKeys } from '../query/queryKeys'
import type { CreatorDiscoveryResponse } from '../types/index'

/**
 * Load the authenticated user's bounded, explainable taste-discovery views.
 *
 * Discovery is an optional exploration mode, so the query only runs when its
 * surface is visible; `enabled` defaults to true for callers that always render
 * it.
 */
export function useCreatorDiscoveries(enabled = true) {
  const { data, isPending, isError, error, refetch } = useQuery<CreatorDiscoveryResponse>({
    queryKey: queryKeys.creators.discoveries(),
    queryFn: () => creatorDiscoveryApi.getDiscoveries(),
    enabled,
  })

  return { data, isPending, isError, error, refetch }
}
