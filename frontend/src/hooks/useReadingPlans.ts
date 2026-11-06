import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invalidateReadingPlans, applyCommittedReadingPlanUpdate } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ContinuityPlan,
  type ContinuityPlanWrite,
} from '../services/api-continuity-plans'
import {
  readingPlanRecoveryApi,
  type RecoveryCandidate,
  type RecoveryStep,
  type PlanRelinkRequest,
  type PlanRelinkResult,
} from '../services/api-reading-plan-recovery'

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

export function useReadingPlanReader(planId: number | null) {
  return useQuery({
    queryKey: planId ? queryKeys.readingPlans.reader(planId) : [],
    queryFn: () => continuityPlansApi.getReader(planId!),
    enabled: planId != null,
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

export function useReadingPlanRecoveryPreview(planId: number | null) {
  return useQuery({
    queryKey: planId ? queryKeys.readingPlans.recovery(planId) : [],
    queryFn: () => readingPlanRecoveryApi.preview(planId!),
    enabled: planId != null,
  })
}

export function useRelinkReadingPlan(planId: number | null, onRecovered?: () => void) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (request: PlanRelinkRequest) =>
      readingPlanRecoveryApi.relink(planId!, request),
    onSuccess: async () => {
      // Invalidate both the recovery preview and the reader view after successful relink
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.readingPlans.recovery(planId!) }),
        client.invalidateQueries({ queryKey: queryKeys.readingPlans.reader(planId!) }),
      ])
      onRecovered?.()
    },
  })
}
