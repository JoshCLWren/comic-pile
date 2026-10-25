/**
 * Render an issue count with correct singular/plural copy.
 *
 * The Queue QA bundle (#3450) found surfaces that always appended "issues",
 * producing "1 issues" in ComicVine results and Map Series confirmations. A
 * shared helper keeps 0, 1, and many consistent instead of fixing one call site
 * at a time.
 *
 * @param count - Number of issues to describe.
 * @returns The count followed by "issue" when exactly one, otherwise "issues".
 */
export function formatIssueCount(count: number): string {
  return `${count} ${count === 1 ? 'issue' : 'issues'}`
}
