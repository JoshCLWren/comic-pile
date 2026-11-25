import Modal from '../../components/Modal'
import type { IssueEditPreviewResponse, IssuePreviewItem } from '../../services/api-issues'

export type PreviewState = {
  range: string
  response: IssueEditPreviewResponse
  selectedStrategy: 'safe_default' | 'numeric_resort'
  acceptedAliasIssueNumbers: string[]
  expectedIssueIds: number[]
}

function PreviewIssueRow({ item }: { item: IssuePreviewItem }) {
  const sourceLists = item.source_lists ?? []
  const effect = item.effect ?? (item.is_new
    ? `new issue #${item.issue_number} inserted at position ${item.position}`
    : `issue #${item.issue_number} at position ${item.position}`)
  return (
    <div
      className="rounded-md border border-white/10 p-2 space-y-1"
      data-testid="preview-issue-row"
    >
      <div className="flex items-start justify-between gap-2">
        <span className={`font-bold ${item.is_new ? 'text-[var(--theme-primary-action)]' : 'text-[var(--theme-text-primary)]'}`}>
          {item.series_title ? `${item.series_title} ` : ''}#{item.issue_number}{item.is_new ? ' (new)' : ''}
        </span>
        <span className="shrink-0 text-stone-500">pos {item.position}</span>
      </div>
      <div className="text-stone-300">{effect}</div>
      {sourceLists.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sourceLists.map((listName) => (
            <span key={listName} className="rounded bg-white/10 px-1.5 py-0.5" data-testid="preview-source-list">
              List: {listName}
            </span>
          ))}
        </div>
      )}
      {(item.is_read || item.has_rating || item.is_mapped || item.is_duplicate || item.frontier_label) && (
        <div className="flex flex-wrap gap-1 text-stone-400">
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

export function IssueEditPreviewModal({
  previewState,
  isPreviewing,
  onClose,
  onToggleAliasOffer,
  onChangeStrategy,
  onConfirm,
}: {
  previewState: PreviewState
  isPreviewing: boolean
  onClose: () => void
  onToggleAliasOffer: (issueNumber: string, accepted: boolean) => void
  onChangeStrategy: (strategy: 'safe_default' | 'numeric_resort') => void
  onConfirm: () => void
}) {
  const outcome = previewState.selectedStrategy === 'numeric_resort'
    ? previewState.response.numeric_resort_outcome
    : previewState.response.default_outcome
  const canCommit = outcome?.can_commit ?? false

  return (
    <Modal
      isOpen
      title="Preview issue changes"
      onClose={onClose}
      data-testid="edit-series-preview-modal"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-muted)]">
          Adding <span className="font-bold text-[var(--theme-text-primary)]">{previewState.range}</span> to {previewState.response.thread_title}.
          Existing relative issue order is preserved by default.
        </p>

        {(previewState.response.alias_offers?.length ?? 0) > 0 && (
          <div className="rounded-xl border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/5 p-3 space-y-2" data-testid="alias-offers">
            <div className="text-sm font-bold text-[var(--theme-text-primary)]">Mapped existing issues need an explicit choice</div>
            <p className="text-xs text-stone-400">
              These requested numbers already exist in this series with identity mapping evidence. Choose alias/mapping instead of creating a duplicate before commit.
            </p>
            {previewState.response.alias_offers!.map((offer) => {
              const accepted = previewState.acceptedAliasIssueNumbers.includes(offer.requested_issue_number)
              return (
                <label key={offer.requested_issue_number} className="flex items-start gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={accepted}
                    disabled={isPreviewing}
                    onChange={(e) => { onToggleAliasOffer(offer.requested_issue_number, e.target.checked) }}
                    data-testid={`alias-offer-${offer.requested_issue_number}`}
                  />
                  <span>
                    <span className="font-bold text-[var(--theme-text-primary)]">#{offer.requested_issue_number}</span>{' '}
                    maps to existing {offer.series_title} #{offer.existing_issue_number} (issue {offer.existing_issue_id}).{' '}
                    {offer.reason}
                  </span>
                </label>
              )
            })}
          </div>
        )}

        <div className="space-y-2">
          <div className={`rounded-xl border p-3 ${previewState.selectedStrategy === 'safe_default' ? 'border-[var(--theme-primary-action)]' : 'border-white/10'}`}>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="radio"
                name="preview-strategy"
                checked={previewState.selectedStrategy === 'safe_default'}
                onChange={() => onChangeStrategy('safe_default')}
                disabled={!previewState.response.default_outcome.can_commit}
              />
              <div className="text-sm">
                <div className="font-bold">Safe default</div>
                <div className="text-xs text-stone-400">
                  {previewState.response.default_outcome.preserves_existing_relative_order
                    ? 'Preserves existing relative issue order.'
                    : 'May change existing relative issue order.'}
                </div>
                {!previewState.response.default_outcome.can_commit && (
                  <div className="text-xs text-[var(--theme-danger)] mt-1" role="alert">
                    {previewState.response.default_outcome.conflict_message ?? 'This change would create a reading-graph cycle.'}
                  </div>
                )}
                {previewState.response.default_outcome.graph.cycles.length > 0 && (
                  <div className="text-xs text-stone-400 mt-1 space-y-1" data-testid="safe-default-cycle-path">
                    {previewState.response.default_outcome.graph.cycles.map((cycle, idx) => (
                      <div key={idx}>
                        {cycle.edges.map((e, i) => (
                          <span key={i}>
                            {i > 0 ? ' -> ' : ''}{e.source.series_title} #{e.source.issue_number}
                            {i === cycle.edges.length - 1 ? ` -> ${e.target.series_title} #${e.target.issue_number}` : ''}
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </label>
          </div>

          {previewState.response.numeric_resort_outcome && (
            <div className={`rounded-xl border p-3 ${previewState.selectedStrategy === 'numeric_resort' ? 'border-[var(--theme-primary-action)]' : 'border-white/10'}`}>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="preview-strategy"
                  checked={previewState.selectedStrategy === 'numeric_resort'}
                  onChange={() => onChangeStrategy('numeric_resort')}
                  disabled={!previewState.response.numeric_resort_outcome.can_commit}
                />
                <div className="text-sm">
                  <div className="font-bold">Numeric resort (explicit)</div>
                  <div className="text-xs text-stone-400">
                    Re-seats ordinary numeric issues in numeric order. Review before saving.
                  </div>
                  {!previewState.response.numeric_resort_outcome.can_commit && (
                    <div className="text-xs text-[var(--theme-danger)] mt-1" role="alert" data-testid="numeric-resort-cycle">
                      {previewState.response.numeric_resort_outcome.conflict_message ?? 'This change would create a reading-graph cycle.'}
                    </div>
                  )}
                  {previewState.response.numeric_resort_outcome.graph.cycles.length > 0 && (
                    <div className="text-xs text-stone-400 mt-1 space-y-1" data-testid="numeric-resort-cycle-path">
                      {previewState.response.numeric_resort_outcome.graph.cycles.map((cycle, idx) => (
                        <div key={idx}>
                          {cycle.edges.map((e, i) => (
                            <span key={i}>
                              {i > 0 ? ' -> ' : ''}{e.source.series_title} #{e.source.issue_number}
                              {i === cycle.edges.length - 1 ? ` -> ${e.target.series_title} #${e.target.issue_number}` : ''}
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </label>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2" data-testid="preview-before-after">
          <div>
            <div className="font-bold text-stone-400 mb-1">Before</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-white/10 p-2 space-y-1">
              {(previewState.selectedStrategy === 'numeric_resort' ? previewState.response.numeric_resort_outcome?.before : previewState.response.default_outcome.before)?.map((item, idx) => (
                <PreviewIssueRow key={`${item.issue_id}-${item.issue_number}-${idx}`} item={item} />
              ))}
            </div>
          </div>
          <div>
            <div className="font-bold text-stone-400 mb-1">After</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-white/10 p-2 space-y-1">
              {(previewState.selectedStrategy === 'numeric_resort' ? previewState.response.numeric_resort_outcome?.after : previewState.response.default_outcome.after)?.map((item, idx) => (
                <PreviewIssueRow key={`${item.issue_id ?? 'new'}-${item.issue_number}-${idx}`} item={item} />
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canCommit}
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-xs font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60 transition-colors"
            data-testid="confirm-preview-add"
          >
            Add issues
          </button>
        </div>
      </div>
    </Modal>
  )
}
