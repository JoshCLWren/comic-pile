import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { creatorMetricDrilldownApi } from '../services/creatorMetricDrilldownApi'
import type { CreatorMetricDrilldown } from '../types/index'
import { queryKeys } from '../query/queryKeys'
import { useMatchMedia } from '../utils/responsive'

export function useCreatorMetricDrilldown(
  creatorKey: string,
  metricType: string,
  params?: {
    role?: string
    ratingValue?: string
    seriesKey?: string
    page?: number
    pageSize?: number
  }
): UseQueryResult<CreatorMetricDrilldown> {
  return useQuery({
    queryKey: queryKeys.creators.metric(creatorKey, metricType, params),
    queryFn: () =>
      creatorMetricDrilldownApi.getMetricDrilldown(creatorKey, metricType, params),
    enabled: !!creatorKey && !!metricType,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Hook to determine whether to show drilldown as a side panel (desktop) or modal (mobile).
 * Uses the responsive utility to check viewport size.
 */
export function useDrilldownPresentation() {
  const isDesktop = useMatchMedia('(min-width: 768px)') // md breakpoint
  
  return {
    isDesktop,
    presentation: isDesktop ? 'side-panel' : 'modal',
  }
}