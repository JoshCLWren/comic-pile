import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { rateApi } from '../../services/api-rate'
import type { Issue } from '../../types'
import { queryClient } from '../../query/queryClient'
import { applyRatedThreadCache } from '../../query/cacheEffects'
import {
  applyIssueReadStatus,
  type IssueMutationSnapshot,
} from './issueMutationState'

interface IssueRateButtonProps {
  issue: Issue
  snapshot: IssueMutationSnapshot
  onSnapshotChange: (snapshot: IssueMutationSnapshot) => void
}

const RATING_VALUES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/** Rate an issue directly from its Thread row without launching Roll (issue #3581). */
export function IssueRateButton({
  issue,
  snapshot,
  onSnapshotChange,
}: IssueRateButtonProps) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedRating, setSavedRating] = useState<number | null>(null)
  // A rating always marks its issue read. Keep the newest snapshot so two rows
  // rated in quick succession both land in the visible issue list.
  const latestSnapshot = useRef(snapshot)
  latestSnapshot.current = snapshot

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
      await applyRatedThreadCache(queryClient, thread)
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
      })
      latestSnapshot.current = nextSnapshot
      onSnapshotChange(nextSnapshot)
      setSavedRating(rating)
      setOpen(false)
    },
    onError: () => {
      setError('Failed to rate')
    },
  })

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-red-400">{error}</span>}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={mutation.isPending}
        aria-expanded={open}
        className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 disabled:opacity-50"
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
              disabled={mutation.isPending}
              aria-label={`Rate issue #${issue.issue_number} ${value} out of 5`}
              className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 disabled:opacity-50"
            >
              {value}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
