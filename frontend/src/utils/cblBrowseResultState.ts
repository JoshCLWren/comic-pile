import type { CBLCatalogBrowsePage } from '../services/api-cbl-sources'
import { catalogSourceCount } from './cblCatalogBrowse'

interface CblBrowseResultStateInput {
  browsePage: CBLCatalogBrowsePage | null
  isPlaceholderData: boolean
  isPending: boolean
  isFetching: boolean
  hasCatalogError: boolean
}

/**
 * Derive catalog totals only from the response for the currently applied
 * folder/search/page key. Placeholder rows remain renderable, but their counts
 * belong to the previous key and must not be presented as current (#3614).
 * Same-key refreshes also withhold the previous totals until new ones settle.
 */
export function cblBrowseResultState({
  browsePage,
  isPlaceholderData,
  isPending,
  isFetching,
  hasCatalogError,
}: CblBrowseResultStateInput) {
  const settledBrowsePage = isPlaceholderData || isFetching ? null : browsePage
  const firstShown =
    settledBrowsePage && settledBrowsePage.items.length > 0
      ? (settledBrowsePage.page - 1) * settledBrowsePage.page_size + 1
      : 0
  const lastShown = settledBrowsePage
    ? (settledBrowsePage.page - 1) * settledBrowsePage.page_size + settledBrowsePage.items.length
    : 0
  const resultCountPending = !hasCatalogError && (isPending || isFetching)
  // Folder pages paginate only their direct sources, while each child folder
  // already carries its recursive total. The applicable folder collection is
  // therefore direct sources plus all child-folder sources, not just this
  // page's direct-source total (#3614/#4171). Searches span the whole catalog.
  const catalogTotal = settledBrowsePage
    ? catalogSourceCount(settledBrowsePage.folders, settledBrowsePage.total)
    : 0
  const resultCountText = hasCatalogError
    ? 'Source list count unavailable.'
    : resultCountPending
      ? 'Updating source list count…'
      : settledBrowsePage
        ? `${settledBrowsePage.scope === 'search' ? settledBrowsePage.total : catalogTotal} of ${settledBrowsePage.scope === 'search' ? settledBrowsePage.catalog_total : catalogTotal} source lists`
        : 'Source list count unavailable.'

  return { settledBrowsePage, firstShown, lastShown, resultCountPending, resultCountText, catalogTotal }
}
