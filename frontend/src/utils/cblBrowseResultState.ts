import type { CBLCatalogBrowsePage } from '../services/api-cbl-sources'

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
 */
export function cblBrowseResultState({
  browsePage,
  isPlaceholderData,
  isPending,
  isFetching,
  hasCatalogError,
}: CblBrowseResultStateInput) {
  const settledBrowsePage = isPlaceholderData ? null : browsePage
  const firstShown =
    settledBrowsePage && settledBrowsePage.items.length > 0
      ? (settledBrowsePage.page - 1) * settledBrowsePage.page_size + 1
      : 0
  const lastShown = settledBrowsePage
    ? (settledBrowsePage.page - 1) * settledBrowsePage.page_size + settledBrowsePage.items.length
    : 0
  const resultCountPending =
    !hasCatalogError && (isPending || (isPlaceholderData && isFetching))
  const resultCountText = hasCatalogError
    ? 'Source list count unavailable.'
    : resultCountPending
      ? 'Updating source list count…'
      : settledBrowsePage
        ? `${settledBrowsePage.total} of ${settledBrowsePage.scope === 'search' ? settledBrowsePage.catalog_total : settledBrowsePage.total} source lists`
        : 'Source list count unavailable.'

  return { settledBrowsePage, firstShown, lastShown, resultCountPending, resultCountText }
}
