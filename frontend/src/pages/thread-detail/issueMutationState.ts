import type { Issue, Thread } from '../../types'

export type IssueReadStatus = 'read' | 'unread'

export interface IssueMutationSnapshot {
  issues: Issue[]
  thread: Thread
}

/**
 * Apply a mark-read or mark-unread result to the currently visible issue page and
 * thread summary without refetching every loaded issue page.
 */
export function applyIssueReadStatus(
  snapshot: IssueMutationSnapshot,
  issueId: number,
  nextStatus: IssueReadStatus,
): IssueMutationSnapshot {
  const currentIssue = snapshot.issues.find((issue) => issue.id === issueId)
  if (!currentIssue || currentIssue.status === nextStatus) {
    return snapshot
  }

  const delta = nextStatus === 'read' ? -1 : 1
  const issuesRemaining = Math.max(0, snapshot.thread.issues_remaining + delta)
  const issues = snapshot.issues.map((issue) =>
    issue.id === issueId ? { ...issue, status: nextStatus } : issue,
  )

  const unreadIssues = issues
    .filter((issue) => issue.status === 'unread')
    .sort((left, right) => left.position - right.position)

  return {
    issues,
    thread: {
      ...snapshot.thread,
      issues_remaining: issuesRemaining,
      next_unread_issue_number:
        unreadIssues[0]?.issue_number ?? snapshot.thread.next_unread_issue_number,
    },
  }
}
