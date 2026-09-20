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
  },
  roll: {
    all: ['roll'] as const,
    bootstrap: () => ['roll', 'bootstrap'] as const,
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
  },
  readerContext: {
    all: ['readerContext'] as const,
    detail: (issueId: number) => ['readerContext', issueId] as const,
  },
  readingPlans: {
    all: ['readingPlans'] as const,
    list: () => ['readingPlans', 'list'] as const,
    detail: (planId: number) => ['readingPlans', 'detail', planId] as const,
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
  customCBLs: {
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
    summaries: (keys: string[]) =>
      ['creators', 'summaries', [...keys].sort()] as const,
  },
  continuityCorrection: {
    groups: () => ['continuityCorrection', 'groups'] as const,
  },
} as const
