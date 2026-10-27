import Modal from '../../components/Modal'

interface ShuffleQueueDialogProps {
  isOpen: boolean
  seriesCount: number
  isPending: boolean
  /**
   * Failure feedback rendered inside the dialog. The shared toast layer paints
   * below open dialogs, so a failure toast on this nearly full-height mobile
   * dialog is invisible — the reason has to live in the dialog itself.
   */
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * In-app confirmation for the whole-queue shuffle. SHUFFLE rewrites every
 * manual ordering in one click, so it is gated by the same `Modal`-based
 * confirmation the destructive delete uses instead of a native
 * `window.confirm`, which is unthemed, blocking, and untestable. The dialog
 * stays open while the mutation runs and on failure so the retry path stays
 * reachable, matching `DeleteThreadDialog`.
 */
export default function ShuffleQueueDialog({
  isOpen,
  seriesCount,
  isPending,
  error = null,
  onConfirm,
  onCancel,
}: ShuffleQueueDialogProps) {
  return (
    <Modal
      isOpen={isOpen}
      title="Shuffle Queue"
      onClose={onCancel}
      data-testid="shuffle-queue-dialog"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-muted)]">
          Shuffle the entire queue? This reorders all {seriesCount} series, including any manual
          order you set. This cannot be undone.
        </p>
        {error && (
          <p
            role="alert"
            data-testid="shuffle-queue-error"
            className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-danger)]"
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
            data-testid="confirm-shuffle-queue"
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-sm font-black text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
          >
            {isPending ? 'Shuffling...' : 'Shuffle Queue'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
