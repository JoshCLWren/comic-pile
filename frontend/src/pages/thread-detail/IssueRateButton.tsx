import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { rateApi } from '../../services/api-rate'
import { undoApi } from '../../services/api-undo'
import { issuesApi } from '../../services/api-issues'
import { threadsApi } from '../../services/api-threads'
import type { Issue, RateUndoInfo } from '../../types'
import { queryClient } from '../../query/queryClient'
import { applyRatedThreadCache } from '../../query/cacheEffects'
import {
  applyIssueReadStatus,
  type IssueMutationSnapshot,
  type IssueReadStatusResult,
} from './issueMutationState'

interface IssueRateButtonProps {
  issue: Issue
  snapshot: IssueMutationSnapshot
  onSnapshotChange: (snapshot: IssueMutationSnapshot) => void
}

const RATING_VALUES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/**
 * Shared treatment for the Rate toggle, its choice buttons, and the
 * row-level Undo. Ratings and the reversal of a rating are personal context,
 * so the controls use the personal-accent theme role with ordinary button
 * typography; the visual grammar reserves the uppercase letter-spaced
 * treatment for eyebrow labels, not action text.
 */
const rateControlClass = [
  'text-xs font-semibold text-[var(--theme-personal-accent)]',
  'transition-opacity hover:opacity-80 disabled:opacity-50',
].join(' ')

/** Rate an issue directly from its Thread row without launching Roll (issue #3581). */
export function IssueRateButton({
  issue,
  snapshot,
  onSnapshotChange,
}: IssueRateButtonProps) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The saved rating belongs to this issue, not to the thread: two rows scored
  // differently must not share one label, and a reload must restore each row's
  // own score (issue #4204, Greptile P1).
  const [savedRating, setSavedRating] = useState<number | null>(
    issue.last_rating ?? null,
  )
  // The rating response names the undo record it wrote, so the row can offer
  // the same Undo Roll ratings get without re-reading a snapshot list.
  const [undoTarget, setUndoTarget] = useState<RateUndoInfo | null>(null)
  // A rating always marks its issue read. Keep the newest snapshot so two rows
  // rated in quick succession both land in the visible issue list.
  const latestSnapshot = useRef(snapshot)
  latestSnapshot.current = snapshot

  async function applyServerIssueState(
    updatedIssue: Issue,
    updatedThread: Awaited<ReturnType<typeof threadsApi.get>>,
  ) {
    const result: IssueReadStatusResult = {
      status: updatedIssue.status,
      read_at: updatedIssue.read_at,
      issues_remaining: updatedThread.issues_remaining,
      next_unread_issue_id: updatedThread.next_unread_issue_id ?? null,
      next_unread_issue_number: updatedThread.next_unread_issue_number ?? null,
      last_rating: updatedIssue.last_rating ?? null,
    }
    const nextSnapshot = applyIssueReadStatus(
      latestSnapshot.current,
      issue.id,
      result,
    )
    latestSnapshot.current = nextSnapshot
    onSnapshotChange(nextSnapshot)
    setSavedRating(updatedIssue.last_rating ?? null)
    await applyRatedThreadCache(queryClient, updatedThread)
  }

  const mutation = useMutation({
    mutationFn: (rating: number) =>
      rateApi.rate({
        thread_id: issue.thread_id,
        rating,
        direct: true,
        issue_number: issue.issue_number,
      }),
    onMutate: () => {
      setError(null)
    },
    onSuccess: async (thread, rating) => {
      // The server marks the rated issue read and advances the thread's
      // unread frontier. Reconcile the visible row from the confirmed
      // response so the adjacent read toggle and remaining count match
      // without a page refresh (Greptile P1).
      const nextSnapshot = applyIssueReadStatus(latestSnapshot.current, issue.id, {
        status: 'read',
        read_at: thread.last_activity_at,
        issues_remaining: thread.issues_remaining,
        next_unread_issue_id: thread.next_unread_issue_id ?? null,
        next_unread_issue_number: thread.next_unread_issue_number ?? null,
        last_rating: rating,
      })
      latestSnapshot.current = nextSnapshot
      onSnapshotChange(nextSnapshot)
      setSavedRating(rating)
      setUndoTarget(thread.undo ?? null)
      setOpen(false)
      await applyRatedThreadCache(queryClient, thread)
    },
    onError: () => {
      setError('Failed to rate')
    },
  })

  const undoMutation = useMutation({
    mutationFn: (target: RateUndoInfo) =>
      undoApi.undo(target.session_id, target.snapshot_id),
    onMutate: () => {
      setError(null)
    },
    onSuccess: async () => {
      // Undo has already reverted the rating and the unread frontier on the
      // server, so repaint the row from the restored server state instead of
      // guessing what the pre-rating values were.
      const [updatedIssue, updatedThread] = await Promise.all([
        issuesApi.get(issue.id),
        threadsApi.get(issue.thread_id),
      ])
      await applyServerIssueState(updatedIssue, updatedThread)
      setUndoTarget(null)
    },
    onError: () => {
      setError('Failed to undo rating')
    },
  })

  const busy = mutation.isPending || undoMutation.isPending

  return (
    <div className="flex items-center gap-2">
      {error && (
        <span role="alert" className="text-xs text-[var(--theme-error)]">
          {error}
        </span>
      )}
      {undoTarget != null && (
        <button
          type="button"
          onClick={() => undoMutation.mutate(undoTarget)}
          disabled={busy}
          aria-label={`Undo rating for issue #${issue.issue_number}`}
          className={rateControlClass}
        >
          {undoMutation.isPending ? 'Undoing…' : 'Undo'}
        </button>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={busy}
        aria-expanded={open}
        className={rateControlClass}
      >
        {savedRating != null ? `Rated ${savedRating}` : 'Rate'}
      </button>
      {open && (
        <div className="flex flex-wrap gap-1">
          {RATING_VALUES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => mutation.mutate(value)}
              disabled={busy}
              aria-label={`Rate issue #${issue.issue_number} ${value} out of 5`}
              className={rateControlClass}
            >
              {value}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
