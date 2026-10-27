/**
 * Canonical in-app thread routes (#3626).
 *
 * Issue-level creator links, eligibility hints, and reading-boundary
 * explanations all need the same copyable URL shape: the Thread route plus the
 * canonical issue id. Keeping the builder and parser here means every entry
 * point produces a URL the Thread page already understands, instead of drifting
 * between `/thread/<id>` and ad-hoc query strings.
 */

/** Route for a thread, optionally deep-linked to one canonical issue. */
export function threadIssueRoutePath(
  threadId: number,
  issueId?: number | null,
): string {
  if (issueId == null || !Number.isInteger(issueId) || issueId <= 0) {
    return `/thread/${threadId}`
  }
  return `/thread/${threadId}?issue=${issueId}#issue-${issueId}`
}

/**
 * Read the `?issue=<id>` deep-link target out of a location search string.
 *
 * Returns `0` when the parameter is absent, empty, or malformed so a bad or
 * stale link degrades to plain thread navigation instead of setting a target
 * row id that can never exist.
 */
export function parseRequestedIssueId(search: string): number {
  const rawIssueId = new URLSearchParams(search).get('issue')
  if (!rawIssueId) return 0
  const parsed = Number(rawIssueId)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0
}
