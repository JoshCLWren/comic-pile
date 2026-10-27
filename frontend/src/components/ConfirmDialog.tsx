import Modal from './Modal'
import type { ReactNode } from 'react'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  /** Body copy naming exactly what the action destroys and what it keeps. */
  children: ReactNode
  confirmLabel: string
  /** Optional pending variant of the confirm label, e.g. "Deleting…". */
  pendingLabel?: string
  cancelLabel?: string
  isPending: boolean
  /** Failure feedback rendered inside the dialog so retry stays reachable. */
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
  testId?: string
}

/**
 * Shared in-page confirmation for destructive actions. Replaces native
 * `window.confirm` dialogs, which browser QA automation cannot see or accept:
 * the harness auto-dismisses them, so an automated delete attempt is
 * indistinguishable from a dead button. The dialog stays open while the
 * action runs and on failure so retry and cancel remain reachable, matching
 * `DeleteThreadDialog`.
 */
export default function ConfirmDialog({
  isOpen,
  title,
  children,
  confirmLabel,
  pendingLabel,
  cancelLabel = 'Cancel',
  isPending,
  error = null,
  onConfirm,
  onCancel,
  testId,
}: ConfirmDialogProps) {
  return (
    <Modal isOpen={isOpen} title={title} onClose={onCancel} data-testid={testId}>
      <div className="space-y-4">
        {children}
        {error && (
          <p
            role="alert"
            className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-danger)]"
            data-testid={testId ? `${testId}-error` : undefined}
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
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            data-testid={testId ? `confirm-${testId}` : undefined}
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
          >
            {isPending && pendingLabel ? pendingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
