import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  continuityPlansApi,
  type ContinuityPlanReadinessResponse,
} from '../services/api-continuity-plans'
import { queryKeys } from '../query/queryKeys';

interface PlanReadinessState {
  readiness: ContinuityPlanReadinessResponse | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

export function usePlanReadiness(
  planId: number | null | undefined,
  refreshKey = 0,
): PlanReadinessState {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.continuityPlans.readiness(planId!, refreshKey),
    queryFn: async () => {
      if (planId == null || !Number.isInteger(planId) || planId <= 0) {
        return null;
      }
      return continuityPlansApi.readiness(planId);
    },
    enabled: planId != null && Number.isInteger(planId) && planId > 0,
  });

  // Handle visibility-based refetching
  useEffect(() => {
    if (planId == null) return
    const onVisible = () => {
      if (document.visibilityState === 'visible') refetch()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [planId, refetch]);

  return {
    readiness: data ?? null,
    isLoading: isPending,
    isError,
    error,
    refetch,
  };
}
