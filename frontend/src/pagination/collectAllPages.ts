/**
 * Safe shared helper that intentionally collects every page of an opaque
 * cursor collection into one flat list.
 *
 * Use this instead of writing a bespoke `while` loop that reassigns a
 * `page_token`. It enforces repeated-token protection (a token is never
 * fetched twice and a server that loops a token terminates the walk) and a
 * bounded safety guard (`maxPages`), so a misbehaving cursor can never
 * drain the collection without limit.
 *
 * Migration targets eat away at `frontend/src/pagination/bespokePagers.baseline.json`;
 * new surfaces must consume this helper or `useInfiniteCollection` instead of
 * hand-writing a drain loop.
 */

/** Default upper bound on the number of pages `collectAllPages` will fetch. */
export const COLLECT_ALL_DEFAULT_MAX_PAGES = 50

/** Why an all-pages walk stopped. */
export type CollectAllStopReason = 'exhausted' | 'max-pages' | 'repeat-token'

export interface CollectAllPagesOptions<TPage, TItem, TToken = string> {
  /** Fetches a single page; `null` requests the first page, otherwise the opaque cursor. */
  fetchPage: (pageToken: TToken | null) => Promise<TPage>
  /** Maps a page payload to its items. */
  selectItems: (page: TPage) => TItem[]
  /** Reads the opaque next-page cursor from a page; `null`/`undefined` means no more pages. */
  selectNextToken: (page: TPage) => TToken | null | undefined
  /** Safety bound on the number of pages fetched. Defaults to `COLLECT_ALL_DEFAULT_MAX_PAGES`. */
  maxPages?: number
}

export interface CollectAllPagesResult<TItem, TPage, TToken = string> {
  items: TItem[]
  pages: TPage[]
  pageCount: number
  /** Truthful reason the walk stopped: exhausted, capped, or a repeated token. */
  stopReason: CollectAllStopReason
}

/**
 * Collects every page of an opaque-cursor collection with repeated-token
 * protection and a bounded safety guard.
 *
 * @param options - Fetch/selection callbacks plus the optional page cap.
 * @returns The flattened items, the raw pages, and the reason the walk stopped.
 */
export async function collectAllPages<TPage, TItem, TToken = string>(
  options: CollectAllPagesOptions<TPage, TItem, TToken>,
): Promise<CollectAllPagesResult<TItem, TPage, TToken>> {
  const maxPages = options.maxPages ?? COLLECT_ALL_DEFAULT_MAX_PAGES
  if (maxPages < 1) {
    throw new RangeError('collectAllPages maxPages must be at least 1')
  }

  const pages: TPage[] = []
  const items: TItem[] = []
  const fetchedTokens = new Set<TToken>()
  let token: TToken | null = null

  for (let pageIndex = 0; pageIndex < maxPages; pageIndex += 1) {
    if (token !== null) {
      if (fetchedTokens.has(token)) {
        return { items, pages, pageCount: pages.length, stopReason: 'repeat-token' }
      }
      fetchedTokens.add(token)
    }

    const page = await options.fetchPage(token)
    pages.push(page)
    items.push(...options.selectItems(page))

    const nextToken = options.selectNextToken(page)
    if (nextToken === null || nextToken === undefined) {
      return { items, pages, pageCount: pages.length, stopReason: 'exhausted' }
    }
    token = nextToken
  }

  return { items, pages, pageCount: pages.length, stopReason: 'max-pages' }
}