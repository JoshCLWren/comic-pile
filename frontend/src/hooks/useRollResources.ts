import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import {
  rollResourcesApi,
  type RollResourcesApi,
} from '../services/rollResourcesApi'

/**
 * Current logical die, ladder and last roll from the scoped native resource.
 * Additive production caller for `GET /v2/roll/die-state`; existing bootstrap
 * reads remain authoritative until Roll migrates surfaces.
 *
 * @param api - Roll resources transport, injectable in tests.
 */
export function useRollDieState(api: RollResourcesApi = rollResourcesApi) {
  return useQuery({
    queryKey: queryKeys.roll.dieState(),
    queryFn: () => api.dieState(),
  })
}

/**
 * Ordered eligible issue identifiers for the current die, with browser-owned
 * temporary snoozes applied exactly as the offer does.
 *
 * @param snoozedThreadIds - Temporary snoozed thread ids, argument, not a URL string.
 * @param api - Roll resources transport, injectable in tests.
 */
export function useRollEligibleIssueIds(
  snoozedThreadIds: readonly number[] = [],
  api: RollResourcesApi = rollResourcesApi,
) {
  return useQuery({
    queryKey: queryKeys.roll.eligibleIssueIds(snoozedThreadIds),
    queryFn: () => api.eligibleIssueIds(snoozedThreadIds),
  })
}

/**
 * Bounded batch of visible issue cards, in first-request order.
 *
 * @param issueIds - Visible issue identifiers for one bounded batch.
 * @param api - Roll resources transport, injectable in tests.
 */
export function useRollIssueCards(
  issueIds: readonly number[],
  api: RollResourcesApi = rollResourcesApi,
) {
  return useQuery({
    queryKey: queryKeys.roll.issueCards(issueIds),
    queryFn: () => api.issueCards(issueIds),
    enabled: issueIds.length > 0,
  })
}
