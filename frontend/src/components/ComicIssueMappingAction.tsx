import ComicVineSearchDialog from './ComicVineSearchDialog'
import Modal from './Modal'
import { useComicIssueMapping } from '../hooks/useComicIssueMapping'
import type { IssueIdentityResponse } from '../services/api-comicvine'

export interface ComicIssueMappingActionProps {
  /** Canonical owned Issue id, or null for a provider-only entry. */
  issueId: number | null
  /** Series title used as the dialog search seed. */
  threadTitle: string
  issueNumber: string | null
  /** Batched identity projection; skips the per-issue identity GET. */
  initialIdentity?: IssueIdentityResponse | null
  /** Whether the identity GET may run when no identity is supplied. */
  fetchEnabled?: boolean
  /** False for provider-only entries: shows Add to ComicPile instead. */
  isOwned?: boolean
  /** Called after confirm/replace/remove so parents can refresh. */
  onMapped?: () => void | Promise<void>
  /** Opens the Add-to-ComicPile flow for provider-only entries. */
  onAddToLibrary?: () => void
  /** Compact treatment for dense rows. */
  compact?: boolean
}

const BASE_BUTTON =
  'inline-flex min-h-11 sm:min-h-9 items-center justify-center rounded-lg px-3 text-xs font-bold transition-colors disabled:opacity-50'

/**
 * Shared ComicVine mapping control for every owned issue card (#4450).
 *
 * An unmapped owned issue always exposes a visible `Map comic` action next to
 * the reading actions — never hidden behind an overflow menu. Mapped issues
 * show a `Mapped` badge with `Change mapping` and a remove affordance, and
 * ambiguous candidates show `Review mapping`. Provider-only entries offer
 * `Add to ComicPile` instead and never call the owner-scoped mapping
 * mutation. The search dialog mounts only after the reader opens it, so
 * rendered lists issue no provider search. Mapping is optional for reading:
 * a failed identity lookup renders a non-blocking status with Retry and
 * never disables the parent card's Read/Rate actions.
 */
export default function ComicIssueMappingAction({
  issueId,
  threadTitle,
  issueNumber,
  initialIdentity,
  fetchEnabled,
  isOwned = true,
  onMapped,
  onAddToLibrary,
  compact = false,
}: ComicIssueMappingActionProps) {
  const mapping = useComicIssueMapping({
    issueId,
    threadTitle,
    issueNumber,
    initialIdentity,
    fetchEnabled,
    isOwned,
    onMapped,
  })

  if (!isOwned) {
    return (
      <span className="inline-flex items-center gap-2" data-testid="comic-mapping-action">
        <button
          type="button"
          onClick={onAddToLibrary}
          className={`${BASE_BUTTON} border border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]`}
        >
          Add to ComicPile
        </button>
      </span>
    )
  }

  const issueLabel = issueNumber ? `issue #${issueNumber}` : 'this issue'
  const statusDot = mapping.isMapped ? 'bg-[var(--theme-comic-accent)]' : 'bg-[var(--theme-text-dim)]'
  const statusText =
    mapping.status === 'mapped'
      ? 'Mapped'
      : mapping.status === 'ambiguous'
        ? 'Mapping needs review'
        : mapping.status === 'error'
          ? 'Mapping status unavailable'
          : mapping.isLoading
            ? 'Checking mapping…'
            : 'Not mapped'

  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="comic-mapping-action">
      <span
        data-testid="comic-mapping-status"
        data-mapping-status={mapping.isMapped ? 'linked' : 'unlinked'}
        className={`inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${
          mapping.isMapped
            ? 'border-[var(--theme-comic-accent)]/30 text-[var(--theme-comic-accent)]'
            : 'border-[var(--theme-border)] text-[var(--theme-text-dim)]'
        }`}
      >
        <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
        {statusText}
      </span>

      {mapping.isError && (
        <button
          type="button"
          onClick={() => void mapping.fetchIdentity()}
          data-testid="comic-mapping-retry"
          className={`${BASE_BUTTON} border border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]`}
        >
          Retry
        </button>
      )}

      {!mapping.isMapped && !mapping.isLoading && (
        <button
          type="button"
          onClick={() => mapping.openMappingDialog('confirm')}
          data-testid="comic-mapping-map"
          aria-label={`Map ${issueLabel} to ComicVine`}
          className={`${BASE_BUTTON} border border-[var(--theme-border)] text-[var(--theme-comic-accent)] hover:bg-[var(--theme-bg-hover)]`}
        >
          {mapping.isAmbiguous ? 'Review mapping' : compact ? 'Map' : 'Map comic'}
        </button>
      )}

      {mapping.isMapped && (
        <>
          <button
            type="button"
            onClick={() => mapping.openMappingDialog('replace')}
            data-testid="comic-mapping-change"
            aria-label={`Change ComicVine mapping for ${issueLabel}`}
            className={`${BASE_BUTTON} border border-[var(--theme-border)] text-[var(--theme-comic-accent)] hover:bg-[var(--theme-bg-hover)]`}
          >
            {compact ? 'Change' : 'Change mapping'}
          </button>
          <button
            type="button"
            onClick={mapping.openRemoveDialog}
            data-testid="comic-mapping-remove"
            aria-label={`Remove ComicVine mapping for ${issueLabel}`}
            className={`${BASE_BUTTON} text-[var(--theme-text-muted)] hover:text-[var(--theme-danger)]`}
          >
            Remove
          </button>
        </>
      )}

      {mapping.isSearchDialogOpen && issueId && (
        <ComicVineSearchDialog
          isOpen
          issueId={issueId}
          threadTitle={threadTitle}
          issueNumber={issueNumber}
          mode={mapping.searchMode}
          onClose={mapping.closeSearchDialog}
          onConfirmed={mapping.handleIdentityConfirmed}
          onSiblingsMapped={mapping.handleSiblingsMapped}
        />
      )}

      <Modal
        isOpen={mapping.isRemoveDialogOpen}
        title="Remove ComicVine mapping?"
        onClose={mapping.closeRemoveDialog}
        data-testid="remove-comicvine-mapping-dialog"
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            This returns {issueLabel} to the &quot;Not mapped&quot; state. You can map it again
            later.
          </p>
          {mapping.removeMappingError && (
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              {mapping.removeMappingError}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={mapping.closeRemoveDialog}
              disabled={mapping.isRemovingMapping}
              className="min-h-11 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] disabled:opacity-50 sm:min-h-9"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void mapping.handleRemoveMapping()}
              disabled={mapping.isRemovingMapping}
              className="min-h-11 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black text-white transition-colors hover:bg-[var(--theme-danger-hover)] disabled:opacity-50 sm:min-h-9"
            >
              {mapping.isRemovingMapping ? 'Removing…' : 'Remove mapping'}
            </button>
          </div>
        </div>
      </Modal>
    </span>
  )
}
