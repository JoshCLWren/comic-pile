interface PlanReadinessPanelProps {
  planId: number | null
  refreshKey?: number
}

/**
 * Standalone plan readiness was removed during incident #2104.
 * Explicit plan nodes/rules remain visible elsewhere in the planner, but the
 * planner no longer runs a second live eligibility evaluation just to render.
 */
export default function PlanReadinessPanel(_props: PlanReadinessPanelProps) {
  return null
}
