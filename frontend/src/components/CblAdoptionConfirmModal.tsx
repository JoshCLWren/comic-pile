import Modal from './Modal'
import type { ContinuityPlanListItem } from '../services/api-continuity-plans'

interface CblAdoptionConfirmModalProps {
  isOpen: boolean
  target: ContinuityPlanListItem | null
  sourceTitle: string | null
  consequenceLine: string | null
  onClose: () => void
  onConfirm: () => void
}

/** Confirm either a new adoption or an explicitly targeted Reading Plan update. */
export function CblAdoptionConfirmModal({
  isOpen,
  target,
  sourceTitle,
  consequenceLine,
  onClose,
  onConfirm,
}: CblAdoptionConfirmModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      title={target ? 'Update this Reading Plan?' : 'Add this reading order?'}
      onClose={onClose}
    >
      <p className="text-sm text-[var(--theme-text-muted)]">
        {target
          ? `Update ${target.name} (Reading Plan #${target.id}) with ${sourceTitle ?? 'this source'}? Only the checked entries are applied; Cancel leaves it unchanged.`
          : sourceTitle
            ? `Add ${sourceTitle} as a Reading Plan? Cancel creates nothing.`
            : 'Add this source as a Reading Plan? Cancel creates nothing.'}
      </p>
      {consequenceLine && (
        <p className="mt-3 text-sm font-bold text-[var(--theme-text-primary)]">{consequenceLine}</p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfirm}
          className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black"
        >
          {target ? 'Update Reading Plan' : 'Add reading order'}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
        >
          Cancel
        </button>
      </div>
    </Modal>
  )
}
