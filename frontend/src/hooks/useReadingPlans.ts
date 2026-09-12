import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invalidateReadingPlans } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ContinuityPlanWrite,
} from '../services/api-continuity-plans'

export function useReadingPlans() {
  return useQuery({
    queryKey: queryKeys.readingPlans.list(),
    queryFn: continuityPlansApi.list,
  })
}

export function useDeleteReadingPlan() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: continuityPlansApi.delete,
    onSuccess: async () => invalidateReadingPlans(client),
  })
}

export function useSaveReadingPlan(planId: number | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ContinuityPlanWrite) =>
      planId
        ? continuityPlansApi.update(planId, payload)
        : continuityPlansApi.create(payload),
    onSuccess: async (plan) => {
      client.setQueryData(queryKeys.readingPlans.detail(plan.id), plan)
      await invalidateReadingPlans(client)
    },
  })
}
