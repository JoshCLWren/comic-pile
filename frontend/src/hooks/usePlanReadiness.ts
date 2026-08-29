import { useQuery } from '@tanstack/react-query'
import {
  continuityPlansApi,
} from '../services/api-continuity-plans'
import { queryKeys } from '../query/queryKeys'

export function usePlanReadiness(
  planId: number | null | undefined,
  refreshKey = 0,
) {
  const enabled = planId != null && Number.isInteger(planId) && planId > 0

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: enabled
      ? [...queryKeys.plan.readiness(planId!), refreshKey]
      : [],
    queryFn: () => continuityPlansApi.readiness(planId!),
    enabled,
    refetchOnWindowFocus: true,
  })

  return {
    readiness: data ?? null,
    isLoading: isPending,
    error: isError ? new Error('Unable to load plan readiness') : null,
    refetch,
  }
}
