import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'

/**
 * One bounded batch projection for the visible issue ids of a list surface
 * (#4444). Mount points call this once per list — never once per row — so
 * cover, rating, read state and mapping status come from a single keyed query.
 * Ids beyond the server bound are split into sequential 200-id chunks by the
 * service, keeping 400+ issue lists at a small bounded request count.
 */
export function useIssueCards(issueIds: number[], options?: { enabled?: boolean }) {
  const normalized = useMemo(
    () => [...new Set(issueIds)].filter((id) => Number.isInteger(id) && id > 0).sort((a, b) => a - b),
    [issueIds],
  )
  return useQuery({
    queryKey: queryKeys.issueCards.list(normalized),
    queryFn: () => issueCardsApi.fetchCards(normalized),
    enabled: (options?.enabled ?? true) && normalized.length > 0,
    staleTime: 30_000,
    // Preserve cached cards for matching canonical ids while an expanded batch loads.
    // Consumers index by issue_id, so old rows cannot masquerade as new issues.
    placeholderData: (previousCards) => previousCards,
  })
}

/** Index a batched projection by issue id for O(1) row lookups. */
export function indexIssueCards(cards: readonly IssueCard[] | undefined): Map<number, IssueCard> {
  const indexed = new Map<number, IssueCard>()
  for (const card of cards ?? []) {
    indexed.set(card.issue_id, card)
  }
  return indexed
}
