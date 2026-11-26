import type { SemanticPreview } from './customCBLBuilderHelpers'

interface Props {
  preview: SemanticPreview
}

export default function CustomCBLChangePreview({ preview }: Props) {
  return (
    <div className="rounded-xl border border-[var(--theme-border)] p-3" aria-live="polite">
      <p className="text-xs font-bold uppercase tracking-wider text-[var(--theme-text-muted)]">Pending change preview</p>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
        First unread before save: {preview.oldFirstUnread ?? 'None'}. After save: {preview.newFirstUnread ?? 'None'}.
      </p>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Cross-list cycle: checked on save; the save is rejected if a new cross-list cycle would be created.</p>
      <ul className="mt-2 space-y-2 text-xs text-[var(--theme-text-primary)]">
        {preview.changed.map((change) => (
          <li key={change.issueId} className="rounded-lg border border-[var(--theme-border)] p-2">
            <p className="font-semibold">{change.label} {change.isNew ? '(inserted)' : change.moved ? '(moved)' : '(updated)'}</p>
            <p>Position: {change.oldPosition ? `#${change.oldPosition}` : 'new'} → #{change.newPosition}</p>
            <p>Former immediate predecessor: {change.oldPrev ?? 'None'}. New immediate predecessor: {change.newPrev ?? 'None'}.</p>
            <p>Wait impact: {change.oldWait.length > 0 ? change.oldWait.join(', ') : 'None'} → {change.newWait.length > 0 ? change.newWait.join(', ') : 'None'}.</p>
          </li>
        ))}
      </ul>
      {preview.totalChanged > preview.changed.length && (
        <p className="mt-2 text-xs text-[var(--theme-text-muted)]">Showing first {preview.changed.length} of {preview.totalChanged} changed entries.</p>
      )}
    </div>
  )
}
