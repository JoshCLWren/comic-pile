import { isString } from '../utils/runtimeChecks'

export type QueueSort = 'position' | 'alphabetical' | 'created'

export interface QueuePageKeyOptions {
  search?: string
  sort: QueueSort
  pageToken?: string | null
  pageSize: number
}

export interface CompletedPageKeyOptions {
  search?: string
  sort: QueueSort
  pageToken?: string | null
  pageSize: number
}

export interface ExcludedPageKeyOptions {
  search?: string
  sort: QueueSort
  pageToken?: string | null
  pageSize: number
}

export interface SessionPageKeyOptions {
  pageToken?: string | null
  pageSize: number
}

export type SessionListParams = Record<string, string | number | boolean | null>

export interface SessionListKeyOptions {
  params?: SessionListParams
}

export interface ThreadIssuePageKeyOptions {
  pageToken?: string | null
  pageSize: number
  status?: 'read' | 'unread'
}

function normalizedSearch(search?: string): string | null {
  const value = search?.trim()
  return value ? value : null
}

function normalizedSessionParams(params?: SessionListParams) {
  if (!params) return {}
  const normalized: SessionListParams = {}
  for (const key of Object.keys(params).sort()) {
    if (key === 'page_token') continue
    const value = params[key]
    if (value == null) continue
    const candidate = isString(value) ? value.trim() : value
    if (candidate === '') continue
    normalized[key] = candidate
  }
  return normalized
}

export const queryKeys = {
  queue: {
    all: ['queue'] as const,
    pages: () => ['queue', 'pages'] as const,
    /**
     * Canonical key for the authoritative active-series total (`active_count`)
     * on its own. Surfaces that need the whole-queue size without loading any
     * page — the Roll shuffle confirmation (#3261) — read this instead of
     * hydrating the paginated list. It sits beside `pages`, not under it, so a
     * bounded count never participates in the queue loader's page reset.
     */
    activeCount: () => ['queue', 'active-count'] as const,
    /**
     * Canonical bounded/infinite Queue list key. `pageToken` is intentionally
     * excluded so the key stays stable across cursor pages; the cursor lives in
     * `pageParam`, not the key. Changing `search`, `sort`, or `pageSize` becomes
     * a distinct query that resets to the first compatible page.
     */
    list: ({ search, sort, pageSize }: { search?: string; sort: QueueSort; pageSize: number }) =>
      ['queue', 'pages', { search: normalizedSearch(search), sort, pageSize }] as const,
    page: ({ search, sort, pageToken, pageSize }: QueuePageKeyOptions) =>
      [
        'queue',
        'pages',
        {
          search: normalizedSearch(search),
          sort,
          pageToken: pageToken ?? null,
          pageSize,
        },
      ] as const,
  },
  /**
   * Series the reader removed from the active queue without deleting (#3807).
   * The rows are untouched, so this list is the discoverable library view they
   * are restored from; it therefore has to be refreshed whenever queue
   * membership changes, and it never participates in the active Queue loader.
   */
  excluded: {
    all: ['excluded'] as const,
    pages: () => ['excluded', 'pages'] as const,
    list: ({ search, sort, pageSize }: { search?: string; sort: QueueSort; pageSize: number }) =>
      ['excluded', 'pages', { search: normalizedSearch(search), sort, pageSize }] as const,
    page: ({ search, sort, pageToken, pageSize }: ExcludedPageKeyOptions) =>
      [
        'excluded',
        'pages',
        {
          search: normalizedSearch(search),
          sort,
          pageToken: pageToken ?? null,
          pageSize,
        },
      ] as const,
  },
  completed: {
    all: ['completed'] as const,
    pages: () => ['completed', 'pages'] as const,
    /**
     * Canonical bounded/infinite Completed list key. `pageToken` is intentionally
     * excluded so the key stays stable across cursor pages; the cursor lives in
     * `pageParam`, not the key. Changing `search`, `sort`, or `pageSize` becomes
     * a distinct query that resets to the first compatible page.
     */
    list: ({ search, sort, pageSize }: { search?: string; sort: QueueSort; pageSize: number }) =>
      ['completed', 'pages', { search: normalizedSearch(search), sort, pageSize }] as const,
    page: ({ search, sort, pageToken, pageSize }: CompletedPageKeyOptions) =>
      [
        'completed',
        'pages',
        {
          search: normalizedSearch(search),
          sort,
          pageToken: pageToken ?? null,
          pageSize,
        },
      ] as const,
  },
  session: {
    all: ['session'] as const,
    current: () => ['session', 'current'] as const,
    pages: () => ['session', 'pages'] as const,
    /**
     * Canonical infinite Session index key. `page_token` is intentionally
     * excluded so the key stays stable across cursor pages; the cursor lives
     * in `pageParam`, not the key. Filter params are normalized so the same
     * filter set always hashes to one stable key.
     */
    list: ({ params }: SessionListKeyOptions = {}) =>
      ['session', 'pages', normalizedSessionParams(params)] as const,
    page: ({ pageToken, pageSize }: SessionPageKeyOptions) =>
      ['session', 'pages', { pageToken: pageToken ?? null, pageSize }] as const,
    detail: (sessionId: number) => ['session', 'detail', sessionId] as const,
    /**
     * Canonical session snapshot list key. The session detail page and the
     * History card count read the same `snapshots` rows, so every
     * snapshot-changing mutation invalidates this space (and `undo.all`, the
     * Roll undo list over the same rows) together. Without that, the session
     * view could keep serving a pre-change list — even an empty one — while
     * History showed the new count (#3468).
     */
    snapshots: (sessionId: number | string) =>
      ['session', 'snapshots', sessionId] as const,
    /** Prefix of every session snapshot list, for scanning invalidations. */
    snapshotsAll: () => ['session', 'snapshots'] as const,
    /**
     * Canonical key for the #2744 correction-sheet example lines. Examples are
     * derived from the reader's own rating history, so this key is invalidated
     * alongside the roll/queue mutations that change that history.
     */
    correctionExamples: () => ['session', 'correction-examples'] as const,
  },
  roll: {
    all: ['roll'] as const,
    bootstrap: () => ['roll', 'bootstrap'] as const,
    /**
     * Canonical key for one paginated Roll exclusion category (issue #3330).
     * The offset cursor lives in `pageParam`, never in the key, so loading the
     * next page of blocked or out-of-pool series appends instead of resetting.
     */
    exclusions: (category: 'blocked' | 'inactive') =>
      ['roll', 'exclusions', category] as const,
  },
  demo: {
    /**
     * Guest demo (#2757) keys. The demo reads seeded product-owned sample data
     * with no user identity, so the keys stay constant and are never
     * invalidated by account-scoped mutations.
     */
    all: ['demo'] as const,
    roll: () => ['demo', 'roll'] as const,
  },
  thread: {
    all: ['thread'] as const,
    list: () => ['thread', 'list'] as const,
    summaries: () => ['thread', 'summary'] as const,
    summary: (threadId: number) => ['thread', 'summary', threadId] as const,
    details: () => ['thread', 'detail'] as const,
    detail: (threadId: number) => ['thread', 'detail', threadId] as const,
    issuePages: (threadId: number) => ['thread', threadId, 'issues'] as const,
    /**
     * Canonical prefix for status-filtered paged issue reads. The filter is
     * appended as `{ status }` so each filter owns a distinct page cursor.
     */
    issuePagesPaged: (threadId: number) =>
      ['thread', threadId, 'issues', 'paged'] as const,
    /** Canonical key for the all-pages-drained issue array (IssueToggleList). */
    issuePagesAll: (threadId: number) =>
      ['thread', threadId, 'issues', 'all'] as const,
    /**
     * Canonical key for the bulk per-issue ComicVine creator-credits read
     * that serves the thread issue list's creator column (#3461). Kept out
     * of the `issuePages` prefix so page-shape cache updates never touch it.
     */
    issueCreators: (threadId: number) =>
      ['thread', threadId, 'issue-creators'] as const,
    issuePage: (
      threadId: number,
      { pageToken, pageSize, status }: ThreadIssuePageKeyOptions,
    ) =>
      [
        'thread',
        threadId,
        'issues',
        {
          pageToken: pageToken ?? null,
          pageSize,
          status: status ?? null,
        },
      ] as const,
  },
  dependencies: {
    all: ['dependencies'] as const,
    list: () => ['dependencies', 'list'] as const,
    forThread: (threadId: number) => ['dependencies', 'thread', threadId] as const,
    blocking: (threadId: number) => ['dependencies', 'blocking', threadId] as const,
    blockingBatch: (threadIds: number[]) =>
      ['dependencies', 'blocking-batch', [...threadIds].sort((a, b) => a - b)] as const,
    connected: (threadId: number) => ['dependencies', 'connected', threadId] as const,
    search: (query: string) => ['dependencies', 'search', normalizedSearch(query)] as const,
    issues: (threadId: number) => ['dependencies', 'issues', threadId] as const,
  },
  readingOrders: {
    all: ['readingOrders'] as const,
    forThread: (threadId: number) => ['readingOrders', 'thread', threadId] as const,
  },
  analytics: {
    all: ['analytics'] as const,
    overview: () => ['analytics', 'overview'] as const,
  },
  comicVine: {
    all: ['comicVine'] as const,
    issueIntelligence: (issueId: number) =>
      ['comicVine', 'issueIntelligence', issueId] as const,
    seriesMappingPreview: (
      originIssueId: number,
      provider: string,
      providerSeriesExternalId: string,
    ) =>
      [
        'comicVine',
        'seriesMappingPreview',
        { originIssueId, provider, providerSeriesExternalId },
      ] as const,
    /**
     * Canonical key for the anchor issue a thread-level Map series repair (issue
     * #2773) derives from the thread's own issues. It is read only while the
     * repair dialog is open, so Queue rendering never pays per-card issue fetches.
     */
    queueSeriesOrigin: (threadId: number) => ['comicVine', 'queueSeriesOrigin', threadId] as const,
    /**
     * Server truth about whether the caller already owns one ComicVine volume.
     * The add-series dialog reads it while the confirm step is open to choose
     * between "already in your queue" and "creates a new series" copy (#3854),
     * so an import must invalidate it whenever it changes that answer.
     */
    importStatus: (volumeId: number) => ['comicVine', 'importStatus', volumeId] as const,
  },
  readerContext: {
    all: ['readerContext'] as const,
    detail: (issueId: number) => ['readerContext', issueId] as const,
  },
  readingPlans: {
    all: ['readingPlans'] as const,
    list: () => ['readingPlans', 'list'] as const,
    detail: (planId: number) => ['readingPlans', 'detail', planId] as const,
    reader: (planId: number) => ['readingPlans', 'reader', planId] as const,
    releaseSources: (planId: number) =>
      ['readingPlans', 'release-sources', planId] as const,
  },
  cblSources: {
    all: ['cblSources'] as const,
    search: (query: string) => ['cblSources', 'search', normalizedSearch(query)] as const,
    preview: (listId: number) => ['cblSources', 'preview', listId] as const,
    adoptionPlan: (
      listId: number,
      seriesDecisions: Record<string, boolean>,
      entryDecisions: Record<string, boolean>,
    ) => [
      'cblSources',
      'adoptionPlan',
      listId,
      Object.entries(seriesDecisions).sort(([a], [b]) => a.localeCompare(b)),
      Object.entries(entryDecisions).sort(([a], [b]) => a.localeCompare(b)),
    ] as const,
  },
  /**
   * Read-only prospective reading graph for a CBL adoption (#4020).
   *
   * The key includes the included source positions and the reader's series
   * answers, so each choice asks the server for the graph that answer produces
   * instead of re-deriving eligibility in the browser.
   */
  readingGraph: {
    all: ['readingGraph'] as const,
    preview: (
      sourceListId: number,
      includedPositions: number[],
      choices: Record<string, string>,
    ) => [
      'readingGraph',
      'preview',
      sourceListId,
      [...includedPositions].sort((left, right) => left - right),
      Object.entries(choices).sort(([left], [right]) => left.localeCompare(right)),
    ] as const,
  },
  customCBLs: {
    readers: () => ['customCBLs', 'reader'] as const,
    reader: (id: number) => ['customCBLs', 'reader', id] as const,
    all: ['customCBLs'] as const,
    list: () => ['customCBLs', 'list'] as const,
    detail: (listId: number) => ['customCBLs', 'detail', listId] as const,
    issueSearch: (query: string) =>
      ['customCBLs', 'issueSearch', normalizedSearch(query)] as const,
  },
  taste: {
    all: ['taste'] as const,
    discoveries: () => ['taste', 'discoveries'] as const,
  },
  tags: {
    all: ['tags'] as const,
    /**
     * Canonical tag list key. `search` is normalized to a trimmed value (or
     * `null` when empty) so the inline picker always hashes one stable key.
     */
    list: (search?: string) => ['tags', 'list', normalizedSearch(search)] as const,
    detail: (tagId: number) => ['tags', 'detail', tagId] as const,
    usage: (tagId: number) => ['tags', 'usage', tagId] as const,
    /**
     * Canonical effective-tags key per target. Effective tags union direct
     * assignments with every inherited parent path (issue #3031); the key is
     * stable per target so assignment mutations can invalidate precisely.
     */
    effective: (targetType: string, targetId: number) =>
      ['tags', 'effective', targetType, targetId] as const,
    /**
     * Canonical bulk effective-tags key for every issue in one thread
     * (issue #3422). It sits under the `tags` prefix so
     * `invalidateAfterTagMutation` refreshes row chips alongside every other
     * effective-tags read.
     */
    effectiveForThreadIssues: (threadId: number) =>
      ['tags', 'effective', 'thread', threadId, 'issues'] as const,
  },
  identityInbox: {
    all: ['identityInbox'] as const,
    list: ({ offset, limit }: { offset: number; limit: number }) =>
      ['identityInbox', 'list', { offset, limit }] as const,
  },
  crossover: {
    all: ['crossover'] as const,
    list: () => ['crossover', 'list'] as const,
    detail: (groupId: number) => ['crossover', 'detail', groupId] as const,
    groups: (threadIds: number[]) =>
      ['crossover', 'groups', [...threadIds].sort((a, b) => a - b)] as const,
    issues: (threadId: number) => ['crossover', 'issues', threadId] as const,
  },
  creator: {
    all: ['creator'] as const,
    /**
     * Canonical bounded creator detail key. The pagination cursor lives in
     * `pageParam`, not the key, so every page of one creator shares the
     * stable prefix and `limit` changes become a distinct query.
     */
    detail: (creatorKey: string, { limit }: { limit: number }) =>
      ['creator', 'detail', creatorKey, { limit }] as const,
  },
  undo: {
    all: ['undo'] as const,
    snapshots: (sessionId: number | string) =>
      ['undo', 'snapshots', sessionId] as const,
  },
  creators: {
    all: ['creators'] as const,
    /**
     * Canonical bounded personal creator discovery key (issue #2774). The
     * pagination cursor lives in `pageParam`, not the key, so every page of
     * one browse selection shares the stable prefix. `search` is normalized to
     * a trimmed value (or `undefined` when empty) so the key stays canonical.
     */
    list: (params: { search?: string; sort?: 'name' | 'ratings_count' | 'average_rating'; limit?: number; minRatings?: number }) =>
      ['creators', 'list', params] as const,
    summaries: (keys: string[]) =>
      ['creators', 'summaries', [...keys].sort()] as const,
    /**
     * Canonical bounded personal creator comparison key (issue #3091).
     * Comparison is limited to 2-4 creators. Keys are sorted for stability.
     */
    compare: (keys: string[]) =>
      ['creators', 'compare', [...keys].sort()] as const,
    /**
     * Canonical bounded creator-team chemistry key (issue #3094). The
     * aggregation covers the authenticated user's whole library, so the key
     * carries no parameters beyond the domain prefix.
     */
    teamChemistry: () => ['creators', 'team-chemistry'] as const,
    /**
     * Canonical bounded personal taste-discovery key (issue #3093). The
     * aggregation covers the authenticated user's whole library, so the key
     * carries no parameters beyond the domain prefix.
     */
    discoveries: () => ['creators', 'discoveries'] as const,
    /**
     * Canonical creator metric drilldown key (issue #3176).
     * Supports different metric types with optional parameters for role, rating value, series, and pagination.
     */
    metric: (
      creatorKey: string,
      metricType: string,
      params?: {
        role?: string
        ratingValue?: string
        seriesKey?: string
        page?: number
        pageSize?: number
      }
    ) => {
      const normalizedParams: Record<string, string | number | undefined> = params ? { ...params } : {}
      // Remove undefined values to keep the key canonical
      Object.keys(normalizedParams).forEach(key => {
        if (normalizedParams[key] === undefined) {
          delete normalizedParams[key]
        }
      })
      return ['creators', 'metric', creatorKey, metricType, normalizedParams] as const
    },
    /**
     * Canonical creator rating distribution drilldown key (issue #3176).
     */
    ratingDistribution: (
      creatorKey: string,
      ratingValue: string,
      params?: { page?: number; pageSize?: number }
    ) => {
      const normalizedParams: Record<string, number | undefined> = params ? { ...params } : {}
      Object.keys(normalizedParams).forEach(key => {
        if (normalizedParams[key] === undefined) {
          delete normalizedParams[key]
        }
      })
      return ['creators', 'ratingDistribution', creatorKey, ratingValue, normalizedParams] as const
    },
    /**
     * Canonical creator role drilldown key (issue #3176).
     */
    roleStats: (
      creatorKey: string,
      role: string,
      params?: { page?: number; pageSize?: number }
    ) => {
      const normalizedParams: Record<string, number | undefined> = params ? { ...params } : {}
      Object.keys(normalizedParams).forEach(key => {
        if (normalizedParams[key] === undefined) {
          delete normalizedParams[key]
        }
      })
      return ['creators', 'roleStats', creatorKey, role, normalizedParams] as const
    },
    /**
     * Canonical creator series drilldown key (issue #3176).
     */
    seriesStats: (
      creatorKey: string,
      seriesKey: string,
      params?: { page?: number; pageSize?: number }
    ) => {
      const normalizedParams: Record<string, number | undefined> = params ? { ...params } : {}
      Object.keys(normalizedParams).forEach(key => {
        if (normalizedParams[key] === undefined) {
          delete normalizedParams[key]
        }
      })
      return ['creators', 'seriesStats', creatorKey, seriesKey, normalizedParams] as const
    },
  },
  continuityCorrection: {
    groups: () => ['continuityCorrection', 'groups'] as const,
  },
  preferences: {
    all: ['preferences'] as const,
    detail: () => ['preferences', 'detail'] as const,
  },
  releases: {
    all: ['releases'] as const,
    pages: () => ['releases', 'pages'] as const,
    /**
     * Canonical infinite Releases list key. `offset` is intentionally
     * excluded so the key stays stable across offset pages; the offset lives
     * in `pageParam`, not the key. Changing `pageSize` becomes a distinct
     * query that resets to the first compatible page.
     */
    list: ({ pageSize }: { pageSize: number }) =>
      ['releases', 'pages', { pageSize }] as const,
    page: ({ offset, limit }: { offset: number; limit: number }) =>
      ['releases', 'pages', { offset, limit }] as const,
  },
  comicvine: {
    /**
     * Canonical ComicVine series search key. `query` is normalized to a trimmed value.
     * `offset` is excluded from the key so pagination stays stable; it lives in `pageParam`.
     */
    search: (query: string, pageSize: number) => ['comicvine', 'series', 'search', normalizedSearch(query), { pageSize }] as const,
    page: (query: string, offset: number, pageSize: number) => 
      ['comicvine', 'series', 'search', normalizedSearch(query), { offset, pageSize }] as const,
  },
} as const
