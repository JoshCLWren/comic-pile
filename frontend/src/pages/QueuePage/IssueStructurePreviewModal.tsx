import Modal from '../../components/Modal'
import type { IssueEditPreviewResponse } from '../../services/api-issues'
import { PreviewIssueRow } from './IssueEditPreviewParts'

/**
 * Before/After preview for a queued delete or reorder (#4654). A4 requires
 * the same exact-order, constraint and affected-issue disclosure these edits
 * already receive from the server-side projection as create/insert receives.
 */
export function IssueStructurePreviewModal({
  kind,
  response,
  isPreviewing,
  onConfirm,
  onCancel,
}: {
  kind: 'delete' | 'reorder'
  response: IssueEditPreviewResponse
  isPreviewing: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const outcome = response.default_outcome
  return (
    <Modal
      isOpen
      title={kind === 'delete' ? 'Preview issue removal' : 'Preview issue reorder'}
      onClose={onCancel}
      data-testid="edit-series-structure-preview-modal"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--theme-text-muted)]">
          {kind === 'delete' ? 'Removing an issue from' : 'Reordering issues in'}{' '}
          <span className="font-bold text-[var(--theme-text-primary)]">{response.thread_title}</span>
          . Review the exact before/after order and affected issues before saving.
        </p>

        {!outcome.can_commit && (
          <div
            className="rounded-lg border border-[var(--theme-danger)] p-3 text-xs text-[var(--theme-danger)]"
            role="alert"
            data-testid="structure-preview-conflict"
          >
            {outcome.conflict_message ?? 'This change would create a reading-graph cycle.'}
          </div>
        )}
        {outcome.graph.cycles.length > 0 && (
          <div className="space-y-1 text-xs text-[var(--theme-text-muted)]" data-testid="structure-preview-cycle-path">
            {outcome.graph.cycles.map((cycle, idx) => (
              <div key={idx}>
                {cycle.edges.map((edge, i) => (
                  <span key={i}>
                    {i > 0 ? ' -> ' : ''}{edge.source.series_title} #{edge.source.issue_number}
                    {i === cycle.edges.length - 1
                      ? ` -> ${edge.target.series_title} #${edge.target.issue_number}`
                      : ''}
                  </span>
                ))}
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2" data-testid="structure-preview-before-after">
          <div>
            <div className="font-bold text-[var(--theme-text-muted)] mb-1">Before</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-[var(--theme-border)] p-2 space-y-1">
              {outcome.before.map((item, idx) => (
                <PreviewIssueRow key={`${item.issue_id}-${item.issue_number}-${idx}`} item={item} />
              ))}
            </div>
          </div>
          <div>
            <div className="font-bold text-[var(--theme-text-muted)] mb-1">After</div>
            <div className="max-h-40 overflow-auto rounded-lg border border-[var(--theme-border)] p-2 space-y-1">
              {outcome.after.map((item, idx) => (
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
            data-testid="cancel-structure-preview"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!outcome.can_commit || isPreviewing}
            className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-xs font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60 transition-colors"
            data-testid="confirm-structure-preview"
          >
            {kind === 'delete' ? 'Remove issue' : 'Reorder issues'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
