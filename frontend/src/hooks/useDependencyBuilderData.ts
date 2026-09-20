import type { IssueListParams } from '../services/api-issues'
import type { Dependency, Issue, IssueListResponse, Thread, ThreadDependenciesResponse, ThreadListResponse } from '../types'

export interface DependencyBuilderDependenciesApi {
  listThreadDependencies: (threadId: number) => Promise<ThreadDependenciesResponse>
  listBlockedThreadIds: () => Promise<number[]>
  createDependency: (payload: {
    sourceType?: 'thread' | 'issue'
    sourceId: number
    targetType?: 'thread' | 'issue'
    targetId: number
  }) => Promise<Dependency>
  deleteDependency: (dependencyId: number) => Promise<void>
  updateDependency: (dependencyId: number, note: string | null) => Promise<Dependency>
}

export interface DependencyBuilderThreadsApi {
  list: (
    params?: { search?: string },
    pageToken?: string | null,
  ) => Promise<ThreadListResponse>
}

export interface DependencyBuilderIssuesApi {
  list: (
    threadId: number,
    params?: IssueListParams,
  ) => Promise<IssueListResponse>
  migrateThread: (
    threadId: number,
    lastIssueRead: number,
    totalIssues: number,
  ) => Promise<Thread>
}

/**
 * Fetch every unread issue for a thread, following pagination.
 *
 * Extracted verbatim from DependencyBuilder so public behavior is unchanged.
 *
 * @param issuesService - Injectable issues API.
 * @param threadId - Thread whose unread issues should be loaded.
 * @returns All unread issues across every page.
 */
export async function fetchAllUnreadIssues(
  issuesService: DependencyBuilderIssuesApi,
  threadId: number,
): Promise<Issue[]> {
  const allIssues: Issue[] = []
  const seenPageTokens = new Set<string>()
  let nextPageToken: string | null = null

  while (true) {
    const params: IssueListParams = {
      status: 'unread',
      page_size: 100,
    }
    if (nextPageToken) {
      params.page_token = nextPageToken
    }
    const data = await issuesService.list(threadId, params)
    allIssues.push(...data.issues)

    if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
      return allIssues
    }

    seenPageTokens.add(data.next_page_token)
    nextPageToken = data.next_page_token
  }
}
