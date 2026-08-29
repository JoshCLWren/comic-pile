import { useEffect } from 'react'
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

const EMPTY_STATE: PlanReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function usePlanReadiness(
  planId: number | null | undefined,
  refreshKey = 0,
): PlanReadinessState {
  const isValid = planId != null && Number.isInteger(planId) && planId > 0
  const { data, isPending, error, refetch } = useQuery({
    queryKey: isValid ? queryKeys.plans.readiness(planId, refreshKey) : [],
    queryFn: async () => {
      try {
        return await continuityPlansApi.readiness(planId!)
      } catch (reason) {
        throw reason instanceof Error ? reason : new Error('Unable to load plan readiness')
      }
    },
    enabled: isValid,
    initialData: null as ContinuityPlanReadinessResponse | null,
  })

  useEffect(() => {
    if (!isValid) return
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void refetch()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [isValid, refetch])

  if (!isValid) return EMPTY_STATE

  return {
    readiness: data ?? null,
    isLoading: isPending,
    error: (error as Error | null) ?? null,
    refetch: () => {
      void refetch()
    },
  }
}
