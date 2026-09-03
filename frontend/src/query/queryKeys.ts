export type QueueSort = 'position' | 'alphabetical' | 'created'

export interface QueuePageKeyOptions {
  search?: string
  sort: QueueSort
  pageToken?: string | null
  pageSize: number
}

export interface SessionPageKeyOptions {
  pageToken?: string | null
  pageSize: number
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

export const queryKeys = {
  cbl: {
    all: ['cbl'] as const,
    list: () => ['cbl', 'list'] as const,
  },
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
  session: {
    all: ['session'] as const,
    current: () => ['session', 'current'] as const,
    pages: () => ['session', 'pages'] as const,
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
    summaries: () => ['thread', 'summary'] as const,
    summary: (threadId: number) => ['thread', 'summary', threadId] as const,
    details: () => ['thread', 'detail'] as const,
    detail: (threadId: number) => ['thread', 'detail', threadId] as const,
    issuePages: (threadId: number) => ['thread', threadId, 'issues'] as const,
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
    forThread: (threadId: number) => ['dependencies', 'thread', threadId] as const,
    blocking: (threadId: number) => ['dependencies', 'blocking', threadId] as const,
    blockingBatch: (threadIds: number[]) =>
      ['dependencies', 'blocking-batch', [...threadIds].sort((a, b) => a - b)] as const,
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
  continuity: {
    all: ['continuity'] as const,
    chains: (nodeType: string, nodeId: number) =>
      ['continuity', 'chains', nodeType, nodeId] as const,
    readiness: (nodeType: string, nodeId: number) =>
      ['continuity', 'readiness', nodeType, nodeId] as const,
  },
  readerContext: {
    all: ['readerContext'] as const,
    detail: (issueId: number) => ['readerContext', issueId] as const,
  },
  plans: {
    all: ['plans'] as const,
    readiness: (planId: number, refreshKey: number = 0) =>
      ['plans', 'readiness', planId, refreshKey] as const,
  },
  taste: {
    all: ['taste'] as const,
    discoveries: () => ['taste', 'discoveries'] as const,
  },
  crossover: {
    all: ['crossover'] as const,
    groups: (threadIds: number[]) =>
      ['crossover', 'groups', [...threadIds].sort((a, b) => a - b)] as const,
  },
  undo: {
    all: ['undo'] as const,
    snapshots: (sessionId: number | string) =>
      ['undo', 'snapshots', sessionId] as const,
  },
} as const
