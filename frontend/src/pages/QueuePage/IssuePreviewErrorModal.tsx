import Modal from '../../components/Modal'

/**
 * Retryable error surface for a failed create/structural preview (#4654,
 * #5852). Extracted from IssueToggleList to respect the repository file-size
 * limit; the wire contract, controls and test ids are unchanged.
 */
export function IssuePreviewErrorModal({
  message,
  range,
  isPreviewing,
  onCancel,
  onRetry,
}: {
  message: string
  range: string
  isPreviewing: boolean
  onCancel: () => void
  onRetry: () => void
}) {
  return (
    <Modal
      isOpen
      title="Preview unavailable"
      onClose={onCancel}
      data-testid="edit-series-preview-error-modal"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-muted)]" role="alert">
          Could not preview <span className="font-bold">{range}</span>: {message}
        </p>
        <p className="text-xs text-[var(--theme-text-muted)]">
          Nothing was changed. You can retry the preview or cancel.
        </p>
        <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onRetry}
            disabled={isPreviewing || !range.trim()}
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-xs font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60 transition-colors"
            data-testid="retry-preview-add"
          >
            Retry preview
          </button>
        </div>
      </div>
    </Modal>
  )
}
