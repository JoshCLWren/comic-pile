import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ContinuityPlanListItem,
} from '../services/api-continuity-plans'
import type { CBLSourceListDiscoveryItem } from '../services/api-cbl-sources'

/** Whether a Reading Plan already contains placements from this exact CBL source. */
export function planMatchesSource(
  plan: Pick<ContinuityPlanListItem, 'source_paths'>,
  source: Pick<CBLSourceListDiscoveryItem, 'source_path'>,
): boolean {
  return plan.source_paths.some(
    (path) =>
      path === source.source_path ||
      path.endsWith(`/${source.source_path}`) ||
      source.source_path.endsWith(`/${path}`),
  )
}

/** Find existing plans that an untargeted adoption could update or collide with. */
function findMatchingAdoptionPlans(
  plans: ContinuityPlanListItem[],
  source: CBLSourceListDiscoveryItem | null,
  sourceTitle: string | null,
): ContinuityPlanListItem[] {
  if (!source || !sourceTitle) return []
  const normalizedTitle = sourceTitle.trim().toLowerCase()
  return plans.filter(
    (plan) =>
      planMatchesSource(plan, source) || plan.name.trim().toLowerCase() === normalizedTitle,
  )
}

/** Load adoption targets and require a fresh, explicit choice for each source. */
export function useCblAdoptionTarget(
  source: CBLSourceListDiscoveryItem | null,
  sourceTitle: string | null,
) {
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null)
  const sourceId = source?.id ?? null
  useEffect(() => {
    setSelectedPlanId(null)
  }, [sourceId])

  const plansQuery = useQuery({
    queryKey: queryKeys.readingPlans.list(),
    queryFn: continuityPlansApi.list,
    enabled: sourceId !== null,
  })
  const matchingPlans = useMemo(
    () => findMatchingAdoptionPlans(plansQuery.data ?? [], source, sourceTitle),
    [plansQuery.data, source, sourceTitle],
  )
  const selectedPlan = matchingPlans.find((plan) => plan.id === selectedPlanId) ?? null

  return {
    plansQuery,
    matchingPlans,
    selectedPlan,
    selectedPlanId,
    sourceAlreadyAdopted: source
      ? matchingPlans.some((plan) => planMatchesSource(plan, source))
      : false,
    planCheckPending: sourceId !== null && (plansQuery.isPending || plansQuery.isFetching),
    planCheckFailed: sourceId !== null && plansQuery.isError,
    mustChooseTarget: matchingPlans.length > 0,
    chooseTarget: setSelectedPlanId,
    resetTarget: () => setSelectedPlanId(null),
  }
}
