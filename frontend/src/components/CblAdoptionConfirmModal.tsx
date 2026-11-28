import Modal from './Modal'

interface CblAdoptionConfirmModalProps {
  isOpen: boolean
  /** The owned canonical Reading List being updated, or null for a first add. */
  listId: number | null
  listName: string | null
  sourceTitle: string | null
  consequenceLine: string | null
  beforeLine: string | null
  afterLine: string | null
  onClose: () => void
  onConfirm: () => void
}

/**
 * Explicit Add/Update boundary for a source-linked, reader-owned Reading List.
 * Nothing is written here: confirmation calls the v2 commit, and Cancel leaves
 * the source, the owned list and the reader's history untouched. Legacy Reading
 * Plans are never shown as a destination (#4023).
 */
export function CblAdoptionConfirmModal({
  isOpen,
  listId,
  listName,
  sourceTitle,
  consequenceLine,
  beforeLine,
  afterLine,
  onClose,
  onConfirm,
}: CblAdoptionConfirmModalProps) {
  const updating = listId !== null
  return (
    <Modal
      isOpen={isOpen}
      title={updating ? 'Update this Reading List?' : 'Add this reading order?'}
      onClose={onClose}
    >
      <p className="text-sm text-[var(--theme-text-muted)]">
        {updating
          ? `Update ${listName ? `${listName} · ` : ''}Reading List #${listId} with ${sourceTitle ?? 'this source'}? Only the checked entries are applied; Cancel leaves the list and your reading history unchanged.`
          : sourceTitle
            ? `Add ${sourceTitle} to a new Reading List you own? Cancel creates nothing.`
            : 'Add this source to a new Reading List you own? Cancel creates nothing.'}
      </p>
      {(beforeLine || afterLine) && (
        <dl className="mt-3 space-y-1 text-sm">
          {beforeLine && (
            <div className="flex flex-wrap gap-1">
              <dt className="font-bold text-[var(--theme-text-primary)]">Before:</dt>
              <dd className="text-[var(--theme-text-muted)]">{beforeLine}</dd>
            </div>
          )}
          {afterLine && (
            <div className="flex flex-wrap gap-1">
              <dt className="font-bold text-[var(--theme-text-primary)]">After:</dt>
              <dd className="text-[var(--theme-text-muted)]">{afterLine}</dd>
            </div>
          )}
        </dl>
      )}
      {consequenceLine && (
        <p className="mt-3 text-sm font-bold text-[var(--theme-text-primary)]">{consequenceLine}</p>
      )}
      <p className="mt-2 text-xs text-[var(--theme-text-dim)]">
        Read status, ratings and manually added comics are preserved.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfirm}
          className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black"
        >
          {updating ? 'Update Reading List' : 'Add reading order'}
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
