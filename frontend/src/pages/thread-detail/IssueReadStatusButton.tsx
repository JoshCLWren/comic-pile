import { useState } from 'react'
import { threadsApi } from '../../services/api'
import { issuesApi } from '../../services/api-issues'
import type { Issue } from '../../types'
import {
  applyIssueReadStatus,
  type IssueMutationSnapshot,
  type IssueReadStatusResult,
} from './issueMutationState'

interface IssueReadStatusButtonProps {
  issue: Issue
  onSnapshotChange: (
    update: (snapshot: IssueMutationSnapshot) => IssueMutationSnapshot,
  ) => void
}

/** Toggle one visible issue and reconcile only the affected row plus thread summary. */
export function IssueReadStatusButton({
  issue,
  onSnapshotChange,
}: IssueReadStatusButtonProps) {
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleToggle() {
    setIsPending(true)
    setError(null)

    try {
      if (issue.status === 'read') {
        await issuesApi.markUnread(issue.id)
      } else {
        await issuesApi.markRead(issue.id)
      }

      const [updatedIssue, updatedThread] = await Promise.all([
        issuesApi.get(issue.id),
        threadsApi.get(issue.thread_id),
      ])
      const result: IssueReadStatusResult = {
        status: updatedIssue.status,
        read_at: updatedIssue.read_at,
        issues_remaining: updatedThread.issues_remaining,
        next_unread_issue_id: updatedThread.next_unread_issue_id ?? null,
        next_unread_issue_number: updatedThread.next_unread_issue_number ?? null,
      }

      onSnapshotChange((currentSnapshot) =>
        applyIssueReadStatus(currentSnapshot, issue.id, result),
      )
    } catch {
      setError('Failed to update issue')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-red-400">{error}</span>}
      <button
        type="button"
        onClick={() => void handleToggle()}
        disabled={isPending}
        className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 disabled:opacity-50"
      >
        {isPending ? 'Saving…' : issue.status === 'read' ? 'Mark unread' : 'Mark read'}
      </button>
    </div>
  )
}
