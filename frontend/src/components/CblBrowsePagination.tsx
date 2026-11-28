import type { CBLCatalogBrowsePage } from '../services/api-cbl-sources'

interface CblBrowsePaginationProps {
  settledBrowsePage: CBLCatalogBrowsePage | null
  firstShown: number
  lastShown: number
  resultCountPending: boolean
  requestedPage: number
  isCommitting: boolean
  onOpenPage: (page: number) => void
}

/** Direct-source range and bounded page navigation for the CBL catalog. */
export function CblBrowsePagination({
  settledBrowsePage,
  firstShown,
  lastShown,
  resultCountPending,
  requestedPage,
  isCommitting,
  onOpenPage,
}: CblBrowsePaginationProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      {settledBrowsePage && settledBrowsePage.items.length > 0 ? (
        <p role="status" className="text-xs text-[var(--theme-text-muted)]">
          Showing {firstShown}–{lastShown} of {settledBrowsePage.total}{' '}
          {settledBrowsePage.total === 1 ? 'source' : 'sources'}
        </p>
      ) : (
        <p className="text-xs text-[var(--theme-text-muted)]">
          {resultCountPending ? 'Updating page results…' : 'Page results unavailable.'}
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onOpenPage(requestedPage - 1)}
          disabled={!settledBrowsePage?.has_previous || isCommitting}
          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
        >
          Previous page
        </button>
        <span className="text-xs text-[var(--theme-text-muted)]">
          {settledBrowsePage
            ? `Page ${settledBrowsePage.page} of ${Math.max(settledBrowsePage.total_pages, 1)}`
            : resultCountPending
              ? 'Updating page…'
              : 'Page unavailable'}
        </span>
        <button
          type="button"
          onClick={() => onOpenPage(requestedPage + 1)}
          disabled={!settledBrowsePage?.has_next || isCommitting}
          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
        >
          Next page
        </button>
      </div>
    </div>
  )
}
