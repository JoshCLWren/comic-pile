import { useState } from 'react'
import { useUndo } from '../../hooks/useUndo'
import { queryClient } from '../../query/queryClient'
import { invalidateAfterUndo } from '../../query/cacheEffects'

interface IssueRatingUndoNoticeProps {
  threadId: number
  issueNumber: string
  rating: number
  sessionId: number
  snapshotId: number
  onUndone: () => void
}

/**
 * Immediate Undo for a rating submitted from a Thread row (#4204).
 *
 * The rate response names the snapshot that owns this rating, so Undo targets
 * exactly that action instead of guessing the newest session snapshot.
 */
export function IssueRatingUndoNotice({
  threadId,
  issueNumber,
  rating,
  sessionId,
  snapshotId,
  onUndone,
}: IssueRatingUndoNoticeProps) {
  const undoMutation = useUndo()
  const [error, setError] = useState<string | null>(null)

  async function handleUndo() {
    setError(null)
    try {
      await undoMutation.mutate({ sessionId, snapshotId })
      await invalidateAfterUndo(queryClient, threadId)
      onUndone()
    } catch {
      setError('Failed to undo rating')
    }
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-xs text-[var(--theme-text-muted)]"
    >
      <span>
        Rated issue #{issueNumber} {rating}/5.
      </span>
      <button
        type="button"
        onClick={() => void handleUndo()}
        disabled={undoMutation.isPending}
        className="text-xs font-semibold text-[var(--theme-personal-accent)] transition-opacity hover:opacity-80 disabled:opacity-50"
      >
        {undoMutation.isPending ? 'Undoing…' : 'Undo'}
      </button>
      {error && (
        <span role="alert" className="text-xs text-[var(--theme-error)]">
          {error}
        </span>
      )}
    </div>
  )
}
