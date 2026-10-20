/**
 * Reading-progress counters for a thread whose issues are tracked individually.
 *
 * A tracked series is only readable when its counters satisfy
 * `0 <= issues_remaining <= total_issues`. Legacy counter threads carry no
 * `total_issues` and report no percentage at all. Counters that break the
 * invariant are reported as `inconsistent` so a renderer states that the
 * counters disagree instead of printing an impossible percentage (#3595:
 * `total_issues=1` with `issues_remaining=36` rendered "-3500%").
 */

/** The two counters every reading-progress surface derives from. */
export interface ReadingProgressCounters {
  total_issues?: number | null
  issues_remaining?: number | null
}

/** The resolved reading-progress state for one set of counters. */
export type ReadingProgress =
  /** The thread has no known total, so no percentage can be derived. */
  | { status: 'untracked' }
  /** The thread is tracked but holds no issues, so there is no progress to show. */
  | { status: 'empty' }
  /** The counters cannot describe a real series and must not be rendered as one. */
  | { status: 'inconsistent' }
  /** The counters describe a real series and can be rendered. */
  | { status: 'known'; percentage: number; readCount: number; totalIssues: number }

/**
 * Resolve a thread's issue counters into a renderable reading-progress state.
 *
 * @param counters - The thread's `total_issues` and `issues_remaining` counters.
 * @returns The reading-progress state for those counters.
 */
export function evaluateReadingProgress(
  counters: ReadingProgressCounters | null | undefined,
): ReadingProgress {
  const totalIssues = counters?.total_issues ?? null
  if (totalIssues === null) return { status: 'untracked' }

  // An absent remaining count means nothing is known to be left to read, which
  // is how the surfaces that only carry a total have always read it. A present
  // but non-finite value is corrupt data, not a missing value.
  const remaining = counters?.issues_remaining ?? 0
  if (!Number.isFinite(totalIssues) || !Number.isFinite(remaining)) {
    return { status: 'inconsistent' }
  }
  if (remaining < 0 || remaining > totalIssues) return { status: 'inconsistent' }
  if (totalIssues <= 0) return { status: 'empty' }

  const readCount = totalIssues - remaining
  return {
    status: 'known',
    percentage: Math.round((readCount / totalIssues) * 100),
    readCount,
    totalIssues,
  }
}
