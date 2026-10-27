import Modal from '../../components/Modal'
import type { ThreadListItem } from '../../types'

interface RemoveThreadDialogProps {
  thread: ThreadListItem | null
  isPending: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Confirmation dialog for removing a series from the queue.
 * The series is excluded, not deleted; its history is preserved.
 */
export default function RemoveThreadDialog({
  thread,
  isPending,
  error,
  onConfirm,
  onCancel,
}: RemoveThreadDialogProps) {
  return (
    <Modal
      isOpen={thread !== null}
      title="Remove from Queue"
      onClose={onCancel}
      data-testid="remove-thread-dialog"
    >
      {thread && (
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Remove{' '}
            <span className="font-bold text-[var(--theme-text-primary)]">{thread.title}</span> from
            the queue? It will no longer appear in the active queue or rolls.
          </p>
          <p className="text-sm text-[var(--theme-text-muted)]">
            This keeps everything: unread and read issues, ratings, notes, tags, and
            ComicVine mappings are untouched. You can restore it later from
            &ldquo;Removed from Queue&rdquo; on this page.
          </p>
          <p className="text-sm text-[var(--theme-text-muted)]">
            To delete the series and its history permanently, cancel and choose{' '}
            <span className="font-bold text-[var(--theme-danger)]">Delete Series</span> instead.
          </p>
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-danger)]"
              data-testid="remove-thread-error"
            >
              {error}
            </p>
          )}
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              type="button"
              onClick={onCancel}
              disabled={isPending}
              className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isPending}
              data-testid="confirm-remove-thread"
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-black text-white hover:bg-[var(--theme-primary-action-hover)] transition-colors disabled:opacity-50"
            >
              {isPending ? 'Removing...' : 'Remove from Queue'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
