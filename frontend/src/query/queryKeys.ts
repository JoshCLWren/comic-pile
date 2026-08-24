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
    snapshots: (sessionId: number | string) => ['session', 'snapshots', sessionId] as const,
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
    stale: ({ days }: { days?: number }) => ['thread', 'stale', { days }] as const,
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
  },
  analytics: {
    all: ['analytics'] as const,
    overview: () => ['analytics', 'overview'] as const,
  },
  undo: {
    all: ['undo'] as const,
    snapshots: (sessionId: number | string) => ['undo', 'snapshots', sessionId] as const,
  },
  continuity: {
    all: ['continuity'] as const,
    readiness: (nodeType: string, nodeId: number) =>
      ['continuity', 'readiness', { nodeType, nodeId }] as const,
    chains: (nodeType: string, nodeId: number) =>
      ['continuity', 'chains', { nodeType, nodeId }] as const,
  },
  dependencyGroups: {
    all: ['dependencyGroups'] as const,
    forThread: (threadId: number) => ['dependencyGroups', 'thread', threadId] as const,
    forThreads: (threadIds: number[]) => ['dependencyGroups', 'threads', threadIds] as const,
  },
  comicVine: {
    all: ['comicVine'] as const,
    issueIntelligence: (issueId: number) => ['comicVine', 'issueIntelligence', issueId] as const,
  },
  continuityPlans: {
    all: ['continuityPlans'] as const,
    readiness: (planId: number, refreshKey: number = 0) => ['continuityPlans', 'readiness', planId, refreshKey] as const,
  },
} as const
