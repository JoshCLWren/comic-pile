import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invalidateReadingPlans, applyCommittedReadingPlanUpdate } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ContinuityPlan,
  type ContinuityPlanWrite,
} from '../services/api-continuity-plans'

export interface SaveReadingPlanApi {
  create: (payload: ContinuityPlanWrite) => Promise<ContinuityPlan>
  update: (planId: number, payload: ContinuityPlanWrite) => Promise<ContinuityPlan>
}

export interface SaveReadingPlanDeps {
  /** Injectable create/update API; defaults to the production continuity plans service. */
  api?: SaveReadingPlanApi
}

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

export function useSaveReadingPlan(planId: number | null, deps: SaveReadingPlanDeps = {}) {
  const { api = continuityPlansApi } = deps
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ContinuityPlanWrite) =>
      planId
        ? api.update(planId, payload)
        : api.create(payload),
    onSuccess: async (plan) => {
      await applyCommittedReadingPlanUpdate(client, plan)
    },
  })
}
