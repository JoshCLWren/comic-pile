import type { IssueEditAliasOffer, IssuePreviewItem } from '../../services/api-issues'

/**
 * One Before/After preview row. Shows the specific series, source-list
 * memberships, read/identity/rating effects, the affected Queue/Roll frontier
 * and duplicate risk — not a bare issue number (#4654).
 */
export function PreviewIssueRow({ item }: { item: IssuePreviewItem }) {
  const sourceLists = item.source_lists ?? []
  const effect = item.effect ?? (item.is_new
    ? `new issue #${item.issue_number} inserted at position ${item.position}`
    : `issue #${item.issue_number} at position ${item.position}`)
  return (
    <div
      className="rounded-md border border-[var(--theme-border)] p-2 space-y-1"
      data-testid="preview-issue-row"
    >
      <div className="flex items-start justify-between gap-2">
        <span className={`font-bold ${item.is_new ? 'text-[var(--theme-primary-action)]' : 'text-[var(--theme-text-primary)]'}`}>
          {item.series_title ? `${item.series_title} ` : ''}#{item.issue_number}{item.is_new ? ' (new)' : ''}
        </span>
        <span className="shrink-0 text-[var(--theme-text-dim)]">pos {item.position}</span>
      </div>
      <div className="text-[var(--theme-text-primary)]">{effect}</div>
      {sourceLists.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sourceLists.map((listName) => (
            <span key={listName} className="rounded bg-[var(--theme-bg-hover)] px-1.5 py-0.5" data-testid="preview-source-list">
              List: {listName}
            </span>
          ))}
        </div>
      )}
      {(item.is_read || item.has_rating || item.is_mapped || item.is_duplicate || item.frontier_label) && (
        <div className="flex flex-wrap gap-1 text-[var(--theme-text-muted)]">
          {item.is_read && <span data-testid="preview-read">Read</span>}
          {item.has_rating && <span data-testid="preview-rating">Rated</span>}
          {item.is_mapped && <span data-testid="preview-mapped">Identity mapped</span>}
          {item.frontier_label && <span data-testid="preview-frontier">{item.frontier_label}</span>}
          {item.is_duplicate && (
            <span className="text-[var(--theme-danger)]" data-testid="preview-duplicate">Possible physical duplicate</span>
          )}
        </div>
      )}
    </div>
  )
}

/** Source-preserving alternatives the reader must review before save (#4654). */
export function AliasOfferList({
  offers,
  accepted,
  onToggle,
}: {
  offers: IssueEditAliasOffer[]
  accepted: string[]
  onToggle: (number: string) => void
}) {
  if (offers.length === 0) return null
  return (
    <div
      className="rounded-xl border border-[var(--theme-warning)] p-3 space-y-2"
      data-testid="preview-alias-offers"
    >
      <div className="text-sm font-bold">Alias instead of a duplicate</div>
      <p className="text-xs text-[var(--theme-text-muted)]">
        These numbers already exist as identity-mapped issues in another series.
        Accept an alias to reuse the source issue; no physical duplicate will be created.
      </p>
      {offers.map((offer) => (
        <label
          key={offer.requested_issue_number}
          className="flex items-start gap-2 text-xs"
          data-testid="preview-alias-offer"
        >
          <input
            type="checkbox"
            checked={accepted.includes(offer.requested_issue_number)}
            onChange={() => onToggle(offer.requested_issue_number)}
            data-testid="accept-alias"
          />
          <span>
            #{offer.requested_issue_number} → {offer.series_title} #{offer.existing_issue_number}
            <span className="block text-[var(--theme-text-muted)]">{offer.evidence}</span>
          </span>
        </label>
      ))}
    </div>
  )
}

/** Post-commit Undo affordance for creates and reorders (#4654, #5852). */
export function PostCreateUndoBar({
  isUndoing,
  onUndo,
}: {
  isUndoing: boolean
  onUndo: () => void
}) {
  return (
    <div
      className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-xs"
      data-testid="edit-series-undo-bar"
    >
      <span className="text-[var(--theme-text-muted)]">Issue changes saved. You can still undo this edit.</span>
      <button
        type="button"
        onClick={onUndo}
        disabled={isUndoing}
        className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 py-1.5 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-60 transition-colors"
        data-testid="undo-edit-add"
      >
        {isUndoing ? 'Undoing…' : 'Undo'}
      </button>
    </div>
  )
}
