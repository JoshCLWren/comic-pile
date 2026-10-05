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
   * Authoritative thread lifecycle status from the post-mutation thread read.
   * `mark_issue_read`/`mark_issue_unread` flip `thread.status` between
   * `completed` and `active`, so this must reach the cache alongside the issue
   * row or the thread STATUS display stays stale until a page reload (#3113).
   */
  thread_status: string
  /**
   * Authoritative `thread.reading_progress` from the same read. The backend
   * updates it in lockstep with `status`, so it is projected together (#3113).
   */
  thread_reading_progress: string | null
}

/**
 * Apply an authoritative mark-read or mark-unread result to the currently visible
 * issue page and thread summary without refetching every loaded issue page.
 *
 * Every thread field the mutation is known to change is projected, not just the
 * unread counters. Dropping `status`/`reading_progress` here is what left the
 * thread detail STATUS panel stale after an inline toggle (#3113).
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
    snapshot.thread.next_unread_issue_number === result.next_unread_issue_number &&
    snapshot.thread.status === result.thread_status &&
    (snapshot.thread.reading_progress ?? null) === result.thread_reading_progress

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
      status: result.thread_status,
      reading_progress: result.thread_reading_progress,
    },
  }
}
