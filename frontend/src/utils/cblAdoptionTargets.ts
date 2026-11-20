import type { ContinuityPlanListItem } from '../services/api-continuity-plans'
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

/** Find plans whose source identity or reader-facing name collides with this adoption. */
export function findMatchingAdoptionPlans(
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
