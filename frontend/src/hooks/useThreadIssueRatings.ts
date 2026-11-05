import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { queryKeys } from '../query/queryKeys'
import { issueCardsApi } from '../services/api-issue-cards'

/**
 * Per-request bound the Rust card projection enforces
 * (`native/roll-service/src/issue_service.rs`, `MAX_CARD_ISSUES`). Larger
 * visible sets are split into sequential chunks that never exceed it.
 */
export const ISSUE_CARDS_BATCH_SIZE = 200

interface ThreadIssueRatingsState {
  /** Effective saved rating keyed by issue id; unrated issues are absent. */
  ratingsByIssueId: Map<number, number>
  isPending: boolean
  isError: boolean
  refetch: () => void
}

/**
 * Bulk read of effective per-issue saved ratings for a thread's visible rows
 * (#4204). One bounded Rust `POST /v2/issues/cards` batch covers every id, so
 * a rated row shows "Rated N" after reload instead of a bare Rate button.
 *
 * Ratings are optional personal context: a failed read returns an empty map
 * and rows fall back to the Rate button rather than breaking the issue list.
 *
 * @param threadId - Thread whose issue ratings are read, or null when disabled
 * @param issueIds - Visible issue ids currently rendered
 * @param enabled - Gates the query (used by collapsed issue sections)
 * @returns The ratings map plus query state conveniences
 */
export function useThreadIssueRatings(
  threadId: number | null,
  issueIds: number[],
  enabled = true,
): ThreadIssueRatingsState {
  const canonicalIds = useMemo(
    () => [...new Set(issueIds)].sort((left, right) => left - right),
    [issueIds],
  )

  const query = useQuery({
    queryKey:
      threadId != null && canonicalIds.length > 0
        ? queryKeys.thread.issueRatings(threadId, canonicalIds)
        : [],
    queryFn: async () => {
      const ratingsByIssueId = new Map<number, number>()
      const chunks: number[][] = []
      for (let index = 0; index < canonicalIds.length; index += ISSUE_CARDS_BATCH_SIZE) {
        chunks.push(canonicalIds.slice(index, index + ISSUE_CARDS_BATCH_SIZE))
      }
      for (const chunk of chunks) {
        const response = await issueCardsApi.cards(chunk)
        for (const card of response.items) {
          if (card.rating != null) {
            ratingsByIssueId.set(card.issue_id, card.rating)
          }
        }
      }
      return ratingsByIssueId
    },
    enabled: threadId != null && enabled && canonicalIds.length > 0,
    retry: false,
  })

  const ratingsByIssueId = useMemo(
    () => query.data ?? new Map<number, number>(),
    [query.data],
  )

  return {
    ratingsByIssueId,
    isPending: query.isPending,
    isError: query.isError,
    refetch: () => {
      void query.refetch()
    },
  }
}
