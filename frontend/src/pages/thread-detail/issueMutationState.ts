import type { Issue, Thread } from '../../types'

export type IssueReadStatus = 'read' | 'unread'

export interface IssueMutationSnapshot {
  issues: Issue[]
  thread: Thread
}

export interface IssueReadStatusResult {
  status: IssueReadStatus
  read_at: string | null
  issues_remaining: number
  next_unread_issue_id: number | null
  next_unread_issue_number: string | null
  /**
   * The issue's own saved rating. Omit it when the action leaves the rating
   * alone (plain read-status toggles); a rating or its undo passes the new
   * value so the row label follows server truth (issue #4204).
   */
  last_rating?: number | null
}

/**
 * Apply an authoritative mark-read, mark-unread, rating, or undo result to the
 * currently visible issue page and thread summary without refetching every
 * loaded issue page.
 */
export function applyIssueReadStatus(
  snapshot: IssueMutationSnapshot,
  issueId: number,
  result: IssueReadStatusResult,
): IssueMutationSnapshot {
  const currentIssue = snapshot.issues.find((issue) => issue.id === issueId)
  if (!currentIssue) {
    return snapshot
  }

  const ratingProvided = result.last_rating !== undefined
  const nextRating = result.last_rating ?? null
  const issueIsUnchanged =
    currentIssue.status === result.status &&
    currentIssue.read_at === result.read_at &&
    (!ratingProvided || (currentIssue.last_rating ?? null) === nextRating)
  const threadIsUnchanged =
    snapshot.thread.issues_remaining === result.issues_remaining &&
    snapshot.thread.next_unread_issue_id === result.next_unread_issue_id &&
    snapshot.thread.next_unread_issue_number === result.next_unread_issue_number

  if (issueIsUnchanged && threadIsUnchanged) {
    return snapshot
  }

  const issues = snapshot.issues.map((issue) =>
    issue.id === issueId
      ? {
          ...issue,
          status: result.status,
          read_at: result.read_at,
          ...(ratingProvided ? { last_rating: nextRating } : {}),
        }
      : issue,
  )

  return {
    issues,
    thread: {
      ...snapshot.thread,
      issues_remaining: result.issues_remaining,
      next_unread_issue_id: result.next_unread_issue_id,
      next_unread_issue_number: result.next_unread_issue_number,
    },
  }
}
