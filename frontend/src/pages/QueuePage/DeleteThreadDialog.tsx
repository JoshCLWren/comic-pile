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
 * Confirmation dialog for deleting an active series from the Queue. Owns no
 * mutation state; the pending thread, pending flag, and error are provided by
 * the page-level action hook so the feedback loop stays in one place.
 */
export default function DeleteThreadDialog({
  thread,
  isPending,
  error,
  onConfirm,
  onCancel,
}: DeleteThreadDialogProps) {
  if (!thread) return null

  return (
    <Modal isOpen title="Delete Series" onClose={onCancel}>
      <div className="space-y-4">
        <p className="text-sm text-stone-300">
          Delete <span className="font-bold">{thread.title}</span> from your queue? This removes
          the series and its reading history.
        </p>
        {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="min-h-11 flex-1 rounded-xl border border-stone-700 text-sm font-black text-stone-300 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="min-h-11 flex-1 rounded-xl bg-red-500 text-sm font-black text-white disabled:opacity-50"
          >
            {isPending ? 'Deleting…' : 'Delete Series'}
          </button>
        </div>
      </div>
    </Modal>
  )
}