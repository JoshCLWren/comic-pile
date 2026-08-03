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
}

/**
 * Apply an authoritative mark-read or mark-unread result to the currently visible
 * issue page and thread summary without refetching every loaded issue page.
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

  const issueIsUnchanged =
    currentIssue.status === result.status && currentIssue.read_at === result.read_at
  const threadIsUnchanged =
    snapshot.thread.issues_remaining === result.issues_remaining &&
    snapshot.thread.next_unread_issue_id === result.next_unread_issue_id &&
    snapshot.thread.next_unread_issue_number === result.next_unread_issue_number

  if (issueIsUnchanged && threadIsUnchanged) {
    return snapshot
  }

  const issues = snapshot.issues.map((issue) =>
    issue.id === issueId
      ? { ...issue, status: result.status, read_at: result.read_at }
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
