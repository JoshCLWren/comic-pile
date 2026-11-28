import Modal from '../../components/Modal'
import type { IssueEditPreviewResponse } from '../../services/api-issues'
import { AliasOfferList, PreviewIssueRow } from './IssueEditPreviewParts'

export type IssueCreatePreviewState = {
  range: string
  response: IssueEditPreviewResponse
  selectedStrategy: 'safe_default' | 'numeric_resort'
}

/**
 * Create/insert preview for Edit Series (#4654). Extracted from IssueToggleList
 * so the issue editor stays within the repository's file-size limit; the wire
 * contract, controls and test ids are unchanged.
 */
export function IssueCreatePreviewModal({
  state,
  isPreviewing,
  acceptedAliasNumbers,
  onSelectStrategy,
  onToggleAlias,
  onConfirm,
  onCancel,
}: {
  state: IssueCreatePreviewState
  isPreviewing: boolean
  acceptedAliasNumbers: string[]
  onSelectStrategy: (strategy: 'safe_default' | 'numeric_resort') => void
  onToggleAlias: (number: string) => void
  onConfirm: () => void
  onCancel: () => void
}) {
  const { response } = state
  const hasUnacceptedAlias = (response.alias_offers ?? []).some(
    (offer) => !acceptedAliasNumbers.includes(offer.requested_issue_number),
  )

  return (
    <Modal
      isOpen
      title="Preview issue changes"
      onClose={onCancel}
      data-testid="edit-series-preview-modal"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-muted)]">
          Adding <span className="font-bold text-[var(--theme-text-primary)]">{state.range}</span> to {response.thread_title}.
          Existing relative issue order is preserved by default.
        </p>

        <div className="space-y-2">
          <div className={`rounded-xl border p-3 ${state.selectedStrategy === 'safe_default' ? 'border-[var(--theme-primary-action)]' : 'border-[var(--theme-border)]'}`}>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="radio"
                name="preview-strategy"
                checked={state.selectedStrategy === 'safe_default'}
                onChange={() => onSelectStrategy('safe_default')}
                disabled={!response.default_outcome.can_commit}
              />
              <div className="text-sm">
                <div className="font-bold">Safe default</div>
                <div className="text-xs text-[var(--theme-text-muted)]">
                  {response.default_outcome.preserves_existing_relative_order
                    ? 'Preserves existing relative issue order.'
                    : 'May change existing relative issue order.'}
                </div>
                {!response.default_outcome.can_commit && (
                  <div className="text-xs text-[var(--theme-danger)] mt-1" role="alert">
                    {response.default_outcome.conflict_message ?? 'This change would create a reading-graph cycle.'}
                  </div>
                )}
                {response.default_outcome.graph.cycles.length > 0 && (
                  <div className="text-xs text-[var(--theme-text-muted)] mt-1 space-y-1" data-testid="safe-default-cycle-path">
                    {response.default_outcome.graph.cycles.map((cycle, idx) => (
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

          {response.numeric_resort_outcome && (
            <div className={`rounded-xl border p-3 ${state.selectedStrategy === 'numeric_resort' ? 'border-[var(--theme-primary-action)]' : 'border-[var(--theme-border)]'}`}>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="preview-strategy"
                  checked={state.selectedStrategy === 'numeric_resort'}
                  onChange={() => onSelectStrategy('numeric_resort')}
                  disabled={!response.numeric_resort_outcome.can_commit}
                />
                <div className="text-sm">
                  <div className="font-bold">Numeric resort (explicit)</div>
                  <div className="text-xs text-[var(--theme-text-muted)]">
                    Re-seats ordinary numeric issues in numeric order. Review before saving.
                  </div>
                  {!response.numeric_resort_outcome.can_commit && (
                    <div className="text-xs text-[var(--theme-danger)] mt-1" role="alert" data-testid="numeric-resort-cycle">
                      {response.numeric_resort_outcome.conflict_message ?? 'This change would create a reading-graph cycle.'}
                    </div>
                  )}
                  {response.numeric_resort_outcome.graph.cycles.length > 0 && (
                    <div className="text-xs text-[var(--theme-text-muted)] mt-1 space-y-1" data-testid="numeric-resort-cycle-path">
                      {response.numeric_resort_outcome.graph.cycles.map((cycle, idx) => (
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

        <AliasOfferList
          offers={response.alias_offers ?? []}
          accepted={acceptedAliasNumbers}
          onToggle={onToggleAlias}
        />

        <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2" data-testid="preview-before-after">
          <div>
            <div className="font-bold text-[var(--theme-text-muted)] mb-1">Before</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-[var(--theme-border)] p-2 space-y-1">
              {(state.selectedStrategy === 'numeric_resort' ? response.numeric_resort_outcome?.before : response.default_outcome.before)?.map((item, idx) => (
                <PreviewIssueRow key={`${item.issue_id}-${item.issue_number}-${idx}`} item={item} />
              ))}
            </div>
          </div>
          <div>
            <div className="font-bold text-[var(--theme-text-muted)] mb-1">After</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-[var(--theme-border)] p-2 space-y-1">
              {(state.selectedStrategy === 'numeric_resort' ? response.numeric_resort_outcome?.after : response.default_outcome.after)?.map((item, idx) => (
                <PreviewIssueRow key={`${item.issue_id ?? 'new'}-${item.issue_number}-${idx}`} item={item} />
              ))}
            </div>
          </div>
        </div>

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
            onClick={onConfirm}
            disabled={!(state.selectedStrategy === 'numeric_resort'
              ? response.numeric_resort_outcome?.can_commit
              : response.default_outcome.can_commit)
              || isPreviewing
              || hasUnacceptedAlias}
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-xs font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60 transition-colors"
            data-testid="confirm-preview-add"
          >
            Add issues
          </button>
        </div>
      </div>
    </Modal>
  )
}
