import type { ContinuityReadinessState } from '../../../hooks/useContinuityReadiness'

interface ContinuityReadinessSummaryProps {
  issueId: number | null | undefined
  readinessState?: ContinuityReadinessState
}

/**
 * Transitional compatibility component for #2104.
 *
 * Roll is authoritative, so an already-selected issue no longer gets a second
 * readiness/verifying/retry gate in the reading context UI.
 */
export function ContinuityReadinessSummary(_props: ContinuityReadinessSummaryProps) {
  return null
}
