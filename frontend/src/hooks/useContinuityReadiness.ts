import type { ContinuityReadinessResponse } from '../services/api-continuity-readiness'

export interface ContinuityReadinessState {
  readiness: ContinuityReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ContinuityReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export interface UseContinuityReadinessOptions {
  /** Retained temporarily for call-site compatibility while readiness is removed. */
  skip?: boolean
}

/**
 * Compatibility shim while the standalone readiness product surface is removed.
 *
 * Roll selection is authoritative. This hook intentionally performs no network
 * request and returns no second eligibility verdict for an already-selected issue.
 */
export function useContinuityReadiness(
  _issueId: number | null | undefined,
  _options: UseContinuityReadinessOptions = {},
): ContinuityReadinessState {
  return EMPTY_STATE
}
