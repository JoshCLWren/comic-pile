import Modal from './Modal'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  isDestructive?: boolean
  onConfirm: () => void
  onCancel: () => void
  'data-testid'?: string
}

/**
 * Shared accessible confirmation dialog for destructive/irreversible actions.
 *
 * Native `window.confirm` is not reliable across every runtime context (for
 * example it is auto-dismissed by browser automation that does not register a
 * `dialog` handler, and it is invisible to DOM/accessibility inspection), so
 * destructive actions that must guarantee a visible, testable confirmation
 * step should use this component instead. Built on the shared `Modal`
 * behavior per the frontend visual grammar's modal/dialog contract.
 */
export default function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = true,
  onConfirm,
  onCancel,
  'data-testid': testId,
}: ConfirmDialogProps) {
  return (
    <Modal isOpen={isOpen} title={title} onClose={onCancel} data-testid={testId}>
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-primary)]">{message}</p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 py-3 rounded-lg border border-solid border-[var(--theme-border)] text-xs font-black uppercase tracking-widest text-[var(--theme-text-muted)] hover:bg-white/5 transition-colors"
            data-testid={testId ? `${testId}-cancel` : undefined}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`flex-1 py-3 rounded-lg text-xs font-black uppercase tracking-widest transition-colors ${
              isDestructive
                ? 'bg-[var(--theme-danger)] hover:bg-[var(--theme-danger-hover)] text-white'
                : 'glass-button'
            }`}
            data-testid={testId ? `${testId}-confirm` : undefined}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
