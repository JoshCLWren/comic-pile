import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  invalidateReadingPlans,
  invalidateReadingPlansAfterCrossTabChange,
  applyCommittedReadingPlanUpdate,
} from '../query/cacheEffects'
import { notifyReadingPlansChanged, subscribeToCrossTabChanges } from '../query/crossTabDataSync'
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

/**
 * Keep an open plans list in sync with plan writes made in other tabs (#5686).
 *
 * Committed plan create/update/delete mutations announce themselves on the
 * cross-tab data channel, so another tab invalidates the plan queries instead
 * of waiting out the 30s `staleTime` (or requiring a manual reload).
 * Re-focusing the tab also refreshes the list, covering browsers without
 * `BroadcastChannel` and tabs that missed a message while suspended. Both
 * paths cancel an older pending read so they cannot reuse pre-commit data.
 */
export function useReadingPlansCrossTabSync(): void {
  const client = useQueryClient()

  useEffect(
    () =>
      subscribeToCrossTabChanges((change) => {
        if (change.type === 'reading-plans-changed') {
          void invalidateReadingPlansAfterCrossTabChange(client)
        }
      }),
    [client],
  )

  useEffect(() => {
    function onTabFocus(): void {
      if (document.visibilityState !== 'visible') return
      void invalidateReadingPlansAfterCrossTabChange(client)
    }
    document.addEventListener('visibilitychange', onTabFocus)
    window.addEventListener('focus', onTabFocus)
    return () => {
      document.removeEventListener('visibilitychange', onTabFocus)
      window.removeEventListener('focus', onTabFocus)
    }
  }, [client])
}

export function useReadingPlanReader(
  planId: number | null,
  options?: { refetchOnWindowFocus?: boolean | 'always' },
) {
  return useQuery({
    queryKey: planId ? queryKeys.readingPlans.reader(planId) : [],
    queryFn: () => continuityPlansApi.getReader(planId!),
    enabled: planId != null,
    // Opt-in per view (#5486): the detail page refreshes on focus, but the
    // legacy edit route must not unmount its draft on a failed background fetch.
    refetchOnWindowFocus: options?.refetchOnWindowFocus ?? false,
  })
}

export function useDeleteReadingPlan() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: continuityPlansApi.delete,
    onSuccess: async () => {
      // Do not make other tabs wait for this tab's local refetches to finish.
      notifyReadingPlansChanged()
      await invalidateReadingPlans(client)
    },
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
