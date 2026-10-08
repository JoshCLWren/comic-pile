import Modal from '../../components/Modal'
import type { Issue } from '../../types'

interface DeleteIssueDialogProps {
  issue: Issue | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * In-app confirmation for deleting an issue from a thread. Replaces the native
 * `window.confirm` flow, which froze the whole page instead of showing a
 * confirmation (issue #3269).
 *
 * Confirming closes the dialog: the pill is already removed optimistically and
 * any failure surfaces in the issue list's inline action error. The dialog
 * must not stay open while a delete settles, because in the Edit Series dialog
 * the delete is a draft that only flushes on Save Changes, and a
 * focus-trapping modal would make that button unreachable.
 */
export default function DeleteIssueDialog({
  issue,
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
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              type="button"
              onClick={onCancel}
              className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              data-testid="confirm-delete-issue"
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-[var(--theme-danger-hover)] transition-colors"
            >
              Delete Issue
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
