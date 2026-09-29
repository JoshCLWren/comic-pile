/**
 * Utility functions for determining natural issue insertion order
 */

/**
 * Check if an issue number is "ordinary numeric" - can be sorted numerically
 * This excludes irregular identifiers like "Annual 1", "½", "-1", etc.
 */
export function isOrdinaryNumericIssue(issueNumber: string): boolean {
  // Must be exactly numeric (no letters, symbols, spaces)
  return /^\d+$/.test(issueNumber)
}

/**
 * Parse issue number as integer if it's ordinary numeric, otherwise return null
 */
export function parseOrdinaryNumericIssue(issueNumber: string): number | null {
  if (!isOrdinaryNumericIssue(issueNumber)) {
    return null
  }
  return parseInt(issueNumber, 10)
}

/**
 * Find the best position to insert new issues into an existing list
 * 
 * @param existingIssues - Current list of issues (must be sorted by position)
 * @param newIssueNumbers - Array of issue numbers to add
 * @returns The issue ID to insert after, or null if should append
 */
export function findNaturalInsertPosition(
  existingIssues: Array<{ id: number; issue_number: string }>,
  newIssueNumbers: string[]
): number | null {
  // Separate ordinary numeric and non-ordinary new issues
  const ordinaryNewIssues = newIssueNumbers.filter(isOrdinaryNumericIssue)
  const nonOrdinaryNewIssues = newIssueNumbers.filter(issue => !isOrdinaryNumericIssue)

  // If no ordinary numeric issues, just append (ambiguous case)
  if (ordinaryNewIssues.length === 0) {
    return null
  }

  // Convert existing issues to comparable format
  const existingOrdinaryIssues = existingIssues
    .map(issue => ({
      id: issue.id,
      issue_number: issue.issue_number,
      numericValue: parseOrdinaryNumericIssue(issue.issue_number)
    }))
    .filter(issue => issue.numericValue !== null) as Array<{
      id: number
      issue_number: string
      numericValue: number
    }>

  // Sort ordinary new issues numerically
  const sortedOrdinaryNewIssues = ordinaryNewIssues
    .map(issue => ({
      issue,
      numericValue: parseOrdinaryNumericIssue(issue)!
    }))
    .sort((a, b) => a.numericValue - b.numericValue)

  // Find the insertion position for the first ordinary new issue
  const firstNewIssue = sortedOrdinaryNewIssues[0]
  if (!firstNewIssue) {
    return null
  }

  // Find where the first new issue should go among existing ordinary issues
  let insertAfterId: number | null = null

  for (const existingIssue of existingOrdinaryIssues) {
    if (existingIssue.numericValue < firstNewIssue.numericValue) {
      // This existing issue comes before our new issue, so we could insert after it
      insertAfterId = existingIssue.id
    } else {
      // This existing issue comes after or at our new issue, so we stop
      break
    }
  }

  // If all existing issues are smaller than our new issue, we insert after the last one
  if (insertAfterId === null && existingOrdinaryIssues.length > 0) {
    insertAfterId = existingOrdinaryIssues[existingOrdinaryIssues.length - 1].id
  }

  // If there are no existing ordinary issues, just append (insert at beginning)
  if (existingOrdinaryIssues.length === 0) {
    return null
  }

  return insertAfterId
}

/**
 * Example usage scenarios:
 * 
 * 1. Adding #2 to #33,#34,#35:
 *    - existingIssues: [{id: 1, issue_number: "33"}, {id: 2, issue_number: "34"}, {id: 3, issue_number: "35"}]
 *    - newIssueNumbers: ["2"]
 *    - Returns: null (since 2 < 33, insert at beginning)
 * 
 * 2. Adding #2 to #1,#3:
 *    - existingIssues: [{id: 1, issue_number: "1"}, {id: 2, issue_number: "3"}]
 *    - newIssueNumbers: ["2"]
 *    - Returns: 1 (insert after issue #1)
 * 
 * 3. Adding #4,#5 to #1,#2,#10:
 *    - existingIssues: [{id: 1, issue_number: "1"}, {id: 2, issue_number: "2"}, {id: 3, issue_number: "10"}]
 *    - newIssueNumbers: ["4", "5"]
 *    - Returns: 2 (insert after issue #2)
 * 
 * 4. Adding "Annual 1" to #1,#2,#3:
 *    - existingIssues: [{id: 1, issue_number: "1"}, {id: 2, issue_number: "2"}, {id: 3, issue_number: "3"}]
 *    - newIssueNumbers: ["Annual 1"]
 *    - Returns: null (ambiguous case, just append)
 */