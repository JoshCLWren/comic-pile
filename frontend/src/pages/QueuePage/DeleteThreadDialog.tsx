import Modal from '../../components/Modal'
import type { Thread } from '../../types'

interface DeleteThreadDialogProps {
  thread: Thread | null
  isPending: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * In-app confirmation for deleting a queue thread. Replaces the native
 * `window.confirm`/`window.alert` flow so destructive deletes always show a
 * clear confirmation and visible success/error feedback instead of silently
 * no-oping. The dialog stays open when the delete fails so the error is
 * actionable: the user can retry or cancel.
 */
export default function DeleteThreadDialog({
  thread,
  isPending,
  error,
  onConfirm,
  onCancel,
}: DeleteThreadDialogProps) {
  return (
    <Modal
      isOpen={thread !== null}
      title="Delete Series"
      onClose={onCancel}
      data-testid="delete-thread-dialog"
    >
      {thread && (
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Are you sure you want to delete{' '}
            <span className="font-bold text-[var(--theme-text-primary)]">{thread.title}</span>? Its
            reading history will be removed. This cannot be undone.
          </p>
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-danger)]"
              data-testid="delete-thread-error"
            >
              {error}
            </p>
          )}
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              type="button"
              onClick={onCancel}
              disabled={isPending}
              className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isPending}
              data-testid="confirm-delete-thread"
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
            >
              {isPending ? 'Deleting...' : 'Delete Series'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}