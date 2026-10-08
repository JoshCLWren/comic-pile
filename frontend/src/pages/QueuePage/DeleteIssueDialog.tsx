import Modal from '../../components/Modal'
import type { Issue } from '../../types'

interface DeleteIssueDialogProps {
  issue: Issue | null
  isPending: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * In-app confirmation for deleting an issue from a thread. Replaces the native
 * `window.confirm` flow so destructive deletes always show a clear confirmation
 * and visible success/error feedback instead of silently no-oping. The dialog
 * stays open when the delete fails so the error is actionable: the user can
 * retry or cancel.
 */
export default function DeleteIssueDialog({
  issue,
  isPending,
  error,
  onConfirm,
  onCancel,
}: DeleteIssueDialogProps) {
  return (
    <Modal
      isOpen={issue !== null}
      title="Delete Issue"
      onClose={onCancel}
      data-testid="delete-issue-dialog"
    >
      {issue && (
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Are you sure you want to delete issue #{issue.issue_number}? This cannot be undone.
          </p>
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-danger)]"
              data-testid="delete-issue-error"
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
              data-testid="confirm-delete-issue"
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
            >
              {isPending ? 'Deleting...' : 'Delete Issue'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}