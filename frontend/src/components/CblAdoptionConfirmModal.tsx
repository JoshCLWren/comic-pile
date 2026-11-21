import Modal from './Modal'
import type { CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'
import type { ContinuityPlanListItem } from '../services/api-continuity-plans'
import type { CblAdoptionTargetChangePreview } from '../utils/cblAdoptionPlan'

interface CblAdoptionConfirmModalProps {
  isOpen: boolean
  target: ContinuityPlanListItem | null
  sourceTitle: string | null
  consequenceLine: string | null
  changePreview: CblAdoptionTargetChangePreview | null
  onClose: () => void
  onConfirm: () => void
}

interface ChangePreviewGroupProps {
  title: string
  description: string
  entries: CBLAdoptionPreviewEntry[]
  initiallyOpen?: boolean
}

/** Show every source entry's target-specific outcome without a giant initial dialog. */
function ChangePreviewGroup({
  title,
  description,
  entries,
  initiallyOpen = false,
}: ChangePreviewGroupProps) {
  return (
    <details open={initiallyOpen} className="rounded-lg border border-[var(--theme-border)] p-3">
      <summary className="cursor-pointer text-sm font-bold text-[var(--theme-text-primary)]">
        {title} ({entries.length})
      </summary>
      <p className="mt-2 text-xs text-[var(--theme-text-muted)]">{description}</p>
      {entries.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-[var(--theme-text-primary)]">
          {entries.map((entry) => (
            <li key={entry.cbl_entry_id} className="flex gap-2">
              <span className="shrink-0 font-mono text-xs text-[var(--theme-text-dim)]">
                {entry.cbl_position}.
              </span>
              <span>
                {entry.series_name} #{entry.issue_number}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}

/** Confirm either a new adoption or an explicitly targeted Reading Plan update. */
export function CblAdoptionConfirmModal({
  isOpen,
  target,
  sourceTitle,
  consequenceLine,
  changePreview,
  onClose,
  onConfirm,
}: CblAdoptionConfirmModalProps) {
  const updatePreviewMissing = target !== null && changePreview === null
  return (
    <Modal
      isOpen={isOpen}
      title={target ? 'Update this Reading Plan?' : 'Add this reading order?'}
      onClose={onClose}
      size={target ? 'large' : 'default'}
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
      {target && changePreview && (
        <section className="space-y-3" aria-labelledby="cbl-target-change-preview-heading">
          <div>
            <h3
              id="cbl-target-change-preview-heading"
              className="text-base font-bold text-[var(--theme-text-primary)]"
            >
              Full change preview
            </h3>
            <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
              {changePreview.preservedStepCount} existing{' '}
              {changePreview.preservedStepCount === 1 ? 'step keeps' : 'steps keep'} their IDs and
              curated order. Exclusions, read states, unrelated entries, and other Reading Plans
              remain unchanged.
            </p>
          </div>
          <ChangePreviewGroup
            title="Will be appended"
            description="Checked entries not already in this plan are appended after its existing steps."
            entries={changePreview.additions}
            initiallyOpen
          />
          <ChangePreviewGroup
            title="Already in this plan; position preserved"
            description="Checked entries already in this plan keep their current positions; only their CBL source provenance is refreshed."
            entries={changePreview.alreadyPresent}
          />
          <ChangePreviewGroup
            title="Not selected; no change"
            description="Unchecked or unresolved entries are not applied and are never removed from this plan."
            entries={changePreview.unchanged}
          />
        </section>
      )}
      {updatePreviewMissing && (
        <p role="alert" className="text-sm text-[var(--theme-error)]">
          Load the full change preview before updating this Reading Plan.
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={updatePreviewMissing}
          className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
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
