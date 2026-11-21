import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import {
  continuityPlansApi,
  type ContinuityPlanListItem,
} from '../services/api-continuity-plans'
import type { CBLSourceListDiscoveryItem } from '../services/api-cbl-sources'
import { isFilesystemSourceLocation } from '../utils/cblSourceDisplay'

/** Apply the same reader-safe path projection as the CBL discovery API. */
function comparableSourcePath(path: string): string {
  const normalized = path.trim().replace(/\\/g, '/')
  const marker = 'CBL-ReadingLists/'
  const markerIndex = normalized.indexOf(marker)
  if (markerIndex >= 0) return normalized.slice(markerIndex + marker.length)
  if (isFilesystemSourceLocation(normalized)) {
    return normalized.split('/').pop() ?? normalized
  }
  return normalized
}

/** Whether a Reading Plan already contains placements from this exact CBL source. */
export function planMatchesSource(
  plan: Pick<ContinuityPlanListItem, 'source_paths'>,
  source: Pick<CBLSourceListDiscoveryItem, 'source_path'>,
): boolean {
  const sourcePath = comparableSourcePath(source.source_path)
  return plan.source_paths.some((path) => comparableSourcePath(path) === sourcePath)
}

/** Find existing plans that an untargeted adoption could update or collide with. */
function findMatchingAdoptionPlans(
  plans: ContinuityPlanListItem[],
  source: CBLSourceListDiscoveryItem | null,
  sourceTitle: string | null,
): ContinuityPlanListItem[] {
  if (!source || !sourceTitle) return []
  const sourceNames = new Set(
    [
      source.name,
      sourceTitle,
      `CBL adoption for ${source.source_path}`,
    ].map((name) => name.trim().toLowerCase()),
  )
  return plans.filter(
    (plan) =>
      planMatchesSource(plan, source) || sourceNames.has(plan.name.trim().toLowerCase()),
  )
}

/** Load adoption targets and require a fresh, explicit choice for each source. */
export function useCblAdoptionTarget(
  source: CBLSourceListDiscoveryItem | null,
  sourceTitle: string | null,
) {
  const sourceId = source?.id ?? null
  const [selection, setSelection] = useState<{
    sourceId: number
    planId: number
  } | null>(null)
  const plansQuery = useQuery({
    queryKey: queryKeys.cblSources.adoptionTargets(sourceId ?? 0),
    queryFn: continuityPlansApi.list,
    enabled: sourceId !== null,
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  const matchingPlans = useMemo(
    () => findMatchingAdoptionPlans(plansQuery.data ?? [], source, sourceTitle),
    [plansQuery.data, source, sourceTitle],
  )
  const selectedPlanId = selection?.sourceId === sourceId ? selection.planId : null
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
    chooseTarget: (planId: number) => {
      if (sourceId !== null) setSelection({ sourceId, planId })
    },
    resetTarget: () => setSelection(null),
  }
}
