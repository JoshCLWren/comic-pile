import { useQuery } from '@tanstack/react-query'
import { cblSourcesApi } from '../services/api-cbl-sources'
import { comicVineApi } from '../services/api-comicvine'
import { queryKeys } from '../query/queryKeys'

/**
 * Trim, drop blanks, and de-duplicate Comic Vine issue IDs while preserving
 * the caller's order.
 *
 * Coverage is measured from distinct exact identities, so a repeated ID must
 * never inflate the compared comic count.
 *
 * @param values - Raw external issue IDs in caller order.
 * @returns Distinct non-blank IDs in first-occurrence order.
 */
export function distinctComicvineIssueIds(values: readonly string[]): string[] {
  const seen = new Set<string>()
  const distinct: string[] = []
  for (const raw of values) {
    const issueId = raw.trim()
    if (!issueId || seen.has(issueId)) continue
    seen.add(issueId)
    distinct.push(issueId)
  }
  return distinct
}

/**
 * Read the confirmed Comic Vine identity state of one reader-owned Issue.
 *
 * @param issueId - ComicPile Issue ID, or null when no Issue is selected.
 * @param enabled - Whether the identity lookup should run.
 * @returns The identity query for the Issue.
 */
export function useCblIssueIdentity(issueId: number | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.comicVine.issueIdentity(issueId ?? 0),
    // SAFETY: the query is enabled only when issueId is non-null, so the
    // callback never runs with a null issue.
    queryFn: () => comicVineApi.getIssueIdentity(issueId as number),
    enabled: enabled && issueId !== null,
  })
}

/**
 * Rank shared CBL source lists that cover the supplied exact Comic Vine IDs.
 *
 * @param comicvineIssueIds - Confirmed Comic Vine issue IDs in intended order.
 * @param enabled - Whether the comparison should run.
 * @returns The comparison query. It stays idle while no ID is confirmed.
 */
export function useCblSourceComparison(comicvineIssueIds: readonly string[], enabled = true) {
  const issueIds = distinctComicvineIssueIds(comicvineIssueIds)
  return useQuery({
    queryKey: queryKeys.cblSources.comparison(issueIds),
    queryFn: () => cblSourcesApi.compare(issueIds),
    enabled: enabled && issueIds.length > 0,
  })
}

/**
 * Read every shared source position that holds one exact Comic Vine issue.
 *
 * @param comicvineIssueId - Confirmed Comic Vine issue ID, or null.
 * @param enabled - Whether the reverse lookup should run.
 * @returns The reverse-lookup query for the issue.
 */
export function useCblComicvineIssueOccurrences(
  comicvineIssueId: string | null,
  enabled = true,
) {
  const issueId = comicvineIssueId?.trim() ?? ''
  return useQuery({
    queryKey: queryKeys.cblSources.comicvineIssue(issueId),
    queryFn: () => cblSourcesApi.findByComicvineIssue(issueId),
    enabled: enabled && issueId.length > 0,
  })
}

/**
 * Compare one owned Reading List's confirmed identities to shared CBL sources.
 *
 * @param listId - Owned Reading List ID, or null.
 * @param enabled - Whether the lookup should run.
 * @returns The Reading List candidate query.
 */
export function useCblReadingListCandidates(listId: number | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cblSources.readingListCandidates(listId ?? 0),
    // SAFETY: the query is enabled only when listId is non-null, so the
    // callback never runs with a null list.
    queryFn: () => cblSourcesApi.readingListCandidates(listId as number),
    enabled: enabled && listId !== null,
  })
}
