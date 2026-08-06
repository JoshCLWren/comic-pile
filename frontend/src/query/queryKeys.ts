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
  session: {
    all: ['session'] as const,
    current: () => ['session', 'current'] as const,
    pages: () => ['session', 'pages'] as const,
    page: ({ pageToken, pageSize }: SessionPageKeyOptions) =>
      ['session', 'pages', { pageToken: pageToken ?? null, pageSize }] as const,
    detail: (sessionId: number) => ['session', 'detail', sessionId] as const,
  },
  queue: {
    all: ['queue'] as const,
    pages: () => ['queue', 'pages'] as const,
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
  },
  analytics: {
    all: ['analytics'] as const,
    overview: () => ['analytics', 'overview'] as const,
  },
} as const
