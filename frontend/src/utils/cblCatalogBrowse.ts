/**
 * Pure helpers for the shared CBL catalog browse view.
 *
 * The browse API reports `total` as the direct sources of the current folder
 * and gives each child folder its own recursive count. Keeping the arithmetic
 * and the stale-position rule here lets the browser render faithful, stable
 * totals without depending on a particular page of results (#4171).
 */

/** A folder row as returned by the catalog browse endpoint. */
export interface CatalogFolderCount {
  total_list_count: number
}

/** The position-relevant fields of one served catalog page. */
export interface CatalogServedPosition {
  scope: string
  query: string | null
  folder: string
  page: number | null
}

/**
 * Count every source in a browse scope: direct sources plus the recursive
 * counts of the folders shown on this page.
 *
 * @param folders - Direct child folders of the served page.
 * @param directTotal - Sources held directly by the served folder.
 * @returns The stable total for the whole served scope.
 */
export function catalogSourceCount(
  folders: readonly CatalogFolderCount[],
  directTotal: number,
): number {
  return folders.reduce((sum, folder) => sum + folder.total_list_count, directTotal)
}

/**
 * Build the reader-facing catalog total line shown at the top level.
 *
 * @param total - Stable source count for the served scope.
 * @param folderCount - Number of direct folders shown.
 * @returns A count line that does not change while paging.
 */
export function catalogTotalLabel(total: number, folderCount: number): string {
  const sources = `${total} ${total === 1 ? 'source' : 'sources'}`
  if (folderCount <= 0) return `${sources} in the shared CBL catalog`
  return `${sources} in the shared CBL catalog across ${folderCount} ${folderCount === 1 ? 'folder' : 'folders'}`
}

/**
 * Decide whether served results belong to an obsolete browse position.
 *
 * `keepPreviousData` intentionally holds the prior page while a new
 * folder/search fetch runs. Those old folders must not appear under a new
 * search banner. A pager clamped by the server keeps the same folder and
 * query, so its result stays visible.
 *
 * @param served - The currently displayed page, or null before first data.
 * @param fetching - Whether a new browse request is in flight.
 * @param folder - Folder in the current URL.
 * @param submittedQuery - Search term in the current URL.
 * @param page - Page in the current URL.
 * @returns True while stale results are on screen.
 */
export function isStaleBrowsePosition(
  served: CatalogServedPosition | null,
  fetching: boolean,
  folder: string,
  submittedQuery: string,
  page: number,
): boolean {
  if (!fetching || served === null) return false
  if (submittedQuery) {
    return served.scope !== 'search' || (served.query ?? '') !== submittedQuery || (served.page ?? 1) !== page
  }
  return served.scope === 'search' || served.folder !== folder || (served.page ?? 1) !== page
}
