import { useQuery } from '@tanstack/react-query'
import {
  continuityPlansApi,
  type ContinuityPlanReadinessResponse,
} from '../services/api-continuity-plans'
import { queryKeys } from '../query/queryKeys'

interface PlanReadinessState {
  readiness: ContinuityPlanReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error
  }
  return new Error('Unable to load plan readiness')
}

export function usePlanReadiness(
  planId: number | null | undefined,
): PlanReadinessState {
  const enabled = planId != null && Number.isInteger(planId) && planId > 0

  const query = useQuery({
    queryKey: queryKeys.continuityPlans.readiness(planId ?? -1),
    queryFn: async () => {
      if (!enabled) {
        throw new Error('No plan ID')
      }
      return continuityPlansApi.readiness(planId)
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })

  return {
    readiness: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ? normalizeError(query.error) : null,
    refetch: query.refetch,
  }
}
