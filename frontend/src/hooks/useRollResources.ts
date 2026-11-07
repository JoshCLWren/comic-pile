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

/**
 * Composed scoped snapshot (die + eligible ids + visible cards) for the
 * next Roll surface migration. Additive only: it is not wired into
 * RollPage yet, so the monolithic bootstrap remains authoritative and
 * no extra prod requests fire until a surface opts in.
 *
 * @param snoozedThreadIds - Temporary snoozed thread ids, argument, not a URL string.
 * @param api - Roll resources transport, injectable in tests.
 */
export function useRollResourceSnapshot(
  snoozedThreadIds: readonly number[] = [],
  api: RollResourcesApi = rollResourcesApi,
) {
  const dieState = useRollDieState(api)
  const eligible = useRollEligibleIssueIds(snoozedThreadIds, api)
  const issueIds = eligible.data?.issue_ids ?? []
  const cards = useRollIssueCards(issueIds, api)
  const isPending = dieState.isPending || eligible.isPending || (issueIds.length > 0 && cards.isPending)
  const isError = dieState.isError || eligible.isError || cards.isError
  return {
    dieState: dieState.data,
    eligibleIssueIds: eligible.data,
    issueCards: cards.data,
    isPending,
    isError,
    refetch: async () => {
      await Promise.all([dieState.refetch(), eligible.refetch(), cards.refetch()])
    },
  }
}
